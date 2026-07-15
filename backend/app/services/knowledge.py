"""Knowledge 读服务。

组织列表 / 详情 / 个人知识三类只读能力。所有 discovery / summary / original
判断**必须**调用 `app.services.permission`，不在此重写权限矩阵。

摘要与字段口径说明：
- summaries 为窄表（summary_type + content）。L3/L4 摘要使用
  `redacted_summary` / `safe_summary` 行作为安全摘要；若 seed 未提供，则回退
  为 None（不暴露普通摘要）。
- `confidence` 未在 knowledge_assets 落地，统一返回 None。
- include_archived=true 当前不额外放行归档资产：权限服务对 archived/deprecated
  作 asset_not_active 处理（发现层拒绝），治理归档视图当前不包含。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import safe_log_exception
from app.db.utils import utc_now
from app.models.identity import Project, User
from app.models.ingest import IngestTask
from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetSummary,
    KnowledgeAssetTag,
    KnowledgeAssetVersion,
)
from app.models.original_access import AccessGrant, OriginalAccessRequest
from app.schemas.enums import (
    AlertSeverity,
    AssetStatus,
    AuditAction,
    AuditLogType,
    AuditRiskLevel,
    ConfidentialityLevel,
    KnowledgeScope,
    ProjectRole,
)
from app.schemas.knowledge import (
    AccessInfoOut,
    CurrentVersionOut,
    KnowledgeDeleteResponse,
    KnowledgeDetailOut,
    KnowledgeListItemOut,
    KnowledgeListResponse,
    MaintainerOut,
    RetryIndexResponse,
    SummaryOut,
)
from app.schemas.permission import (
    DEFAULT_POLICY,
    AccessLayer,
    CallerContext,
    DefaultAccessPolicy,
    DeniedReason,
)
from app.services import audit as audit_service
from app.services import error_catalog, indexing, original_access
from app.services.permission import decide, discovery_filter
from app.services.permission_rules import load_access_policy
from app.services.storage import LocalFileStorage
from app.services.weknora_client import (
    NullWeKnoraClient,
    WeKnoraClient,
    weknora_enabled,
)

_logger = logging.getLogger(__name__)


def _index_user_message(ver) -> str | None:
    """index_failed 版本的用户态安全文案——始终按当前目录从 index_error_code 重新派生，
    避免历史 DB 里的旧 / 脏文案继续外显。其它状态返回 None。"""
    if ver is None or ver.index_status != "index_failed":
        return None
    return error_catalog.user_message(ver.index_error_code)


_INACTIVE_STATUSES = ["processing", AssetStatus.archived.value, AssetStatus.deprecated.value]
_DELETED_STATUS = AssetStatus.deleted.value
_REDACTED_LEVELS = {ConfidentialityLevel.L3.value, ConfidentialityLevel.L4.value}


def _can_delete(caller: CallerContext, asset: KnowledgeAsset) -> bool:
    """受控删除权限。

    - 纯 admin（非业务用户）：永不获得业务删除权。
    - personal：仅 owner 本人。
    - project：仅该项目 active project_manager（coach / consultant 不可，除非同时是 active PM）。
    - company：仅 boss / 咨询总监。
    已删除资产不可再删。
    """
    if asset.asset_status == _DELETED_STATUS:
        return False
    if not caller.is_business_user:
        return False
    scope = asset.scope
    if scope == KnowledgeScope.personal.value:
        return asset.owner_user_id == caller.user_id
    if scope == KnowledgeScope.project.value:
        return (
            asset.project_id is not None
            and caller.active_project_roles.get(asset.project_id)
            == ProjectRole.project_manager.value
        )
    if scope == KnowledgeScope.company.value:
        return caller.can_discover_l5  # boss / consulting_director
    return False


_RETRYABLE_INDEX_STATUSES = {"index_failed", "not_indexed", "skipped"}


def can_retry_index(caller: CallerContext, asset: KnowledgeAsset) -> bool:
    """底座索引重试权限。

    项目资产仅允许 active 项目经理；公司治理角色不因公司职务跨项目重试。
    纯 admin（非业务用户）永不获得业务重试权（不因系统身份触达业务原文）。
    - personal：仅 owner 本人。
    - project：active project_manager。
    - company：仅总经理 / 咨询总监。
    已删除资产不可重试。
    """
    if asset.asset_status == _DELETED_STATUS:
        return False
    if not caller.is_business_user:
        return False
    scope = asset.scope
    if scope == KnowledgeScope.personal.value:
        return asset.owner_user_id == caller.user_id
    if scope == KnowledgeScope.project.value:
        return (
            asset.project_id is not None
            and caller.active_project_roles.get(asset.project_id)
            == ProjectRole.project_manager.value
        )
    if scope == KnowledgeScope.company.value:
        return caller.can_discover_l5
    return False


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    """构造带 denied_reason 的错误（detail 内含 denied_reason，供前端读取）。"""
    return HTTPException(
        status_code=status_code, detail={"denied_reason": reason, "message": message}
    )


def _summary_map(asset: KnowledgeAsset) -> dict[str, str | None]:
    """把资产的 summaries（窄表）整理为 {summary_type: content}。"""
    return {s.summary_type: s.content for s in asset.summaries}


def _select_summary_text(level: str, smap: dict[str, str | None]) -> str | None:
    """列表用的单段摘要文本（按保密级别选择安全摘要）。"""
    if level in _REDACTED_LEVELS:
        return smap.get("redacted_summary") or smap.get("safe_summary")
    return smap.get("one_liner") or smap.get("detailed")


def _build_access_info(
    caller: CallerContext,
    asset: KnowledgeAsset,
    *,
    has_grant: bool = False,
    grant_expires_at=None,
    pending_request: bool = False,
    index_status: str | None = None,
    policy: DefaultAccessPolicy = DEFAULT_POLICY,
) -> AccessInfoOut:
    """基于权限服务的三层决策构建 access_info。"""
    o = decide(caller, asset, AccessLayer.original, has_original_grant=has_grant, policy=policy)
    d = decide(caller, asset, AccessLayer.discovery, has_original_grant=has_grant, policy=policy)
    s = decide(caller, asset, AccessLayer.summary, has_original_grant=has_grant, policy=policy)
    # 放行来源取已放行的最高层级来源（三层放行时来源一致，取 discovery 即可）。
    source = d.effective_access_source.value if d.allowed else "none"
    # 可申请：无原文权且为「需申请」软拒绝，且当前没有 pending 申请。
    can_request = (
        (not o.allowed)
        and o.denied_reason == DeniedReason.original_requires_request
        and not pending_request
    )
    return AccessInfoOut(
        discovery=d.allowed,
        summary=s.allowed,
        original=o.allowed,
        effective_source=source,
        can_request_original=can_request,
        existing_request_status="pending" if pending_request else None,
        existing_grant_expires_at=grant_expires_at if has_grant else None,
        can_delete=_can_delete(caller, asset),
        can_retry_index=(
            can_retry_index(caller, asset) and index_status in _RETRYABLE_INDEX_STATUSES
        ),
    )


async def _aux_maps(
    session: AsyncSession, assets: list[KnowledgeAsset]
) -> tuple[dict[uuid.UUID, str], dict[uuid.UUID, str]]:
    """批量加载资产涉及的项目名与维护人姓名，避免 N+1。"""
    project_ids = {a.project_id for a in assets if a.project_id}
    user_ids = {a.maintainer_user_id for a in assets if a.maintainer_user_id}
    projects: dict[uuid.UUID, str] = {}
    users: dict[uuid.UUID, str] = {}
    if project_ids:
        rows = (
            await session.execute(
                select(Project.id, Project.name).where(Project.id.in_(project_ids))
            )
        ).all()
        projects = {r[0]: r[1] for r in rows}
    if user_ids:
        rows = (
            await session.execute(select(User.id, User.name).where(User.id.in_(user_ids)))
        ).all()
        users = {r[0]: r[1] for r in rows}
    return projects, users


async def _version_index_map(
    session: AsyncSession, assets: list[KnowledgeAsset]
) -> dict[uuid.UUID, KnowledgeAssetVersion]:
    """批量加载各资产 current_version 的安全索引状态字段，key=current_version_id。"""
    vids = {a.current_version_id for a in assets if a.current_version_id}
    if not vids:
        return {}
    rows = (
        (
            await session.execute(
                select(KnowledgeAssetVersion).where(KnowledgeAssetVersion.id.in_(vids))
            )
        )
        .scalars()
        .all()
    )
    return {v.id: v for v in rows}


def _to_list_item(
    caller: CallerContext,
    asset: KnowledgeAsset,
    projects: dict[uuid.UUID, str],
    granted_ids: set[uuid.UUID] | None = None,
    vindex: dict[uuid.UUID, KnowledgeAssetVersion] | None = None,
    policy: DefaultAccessPolicy = DEFAULT_POLICY,
    summary_map: dict[str, str | None] | None = None,
) -> KnowledgeListItemOut:
    ver = (vindex or {}).get(asset.current_version_id) if asset.current_version_id else None
    access = _build_access_info(
        caller,
        asset,
        has_grant=bool(granted_ids and asset.id in granted_ids),
        index_status=ver.index_status if ver else None,
        policy=policy,
    )
    smap = summary_map if summary_map is not None else _summary_map(asset)
    summary_text = (
        _select_summary_text(asset.confidentiality_level, smap) if access.summary else None
    )
    return KnowledgeListItemOut(
        id=asset.id,
        title=asset.title,
        scope=asset.scope,
        zone=asset.zone,
        asset_type=asset.asset_type,
        confidentiality_level=asset.confidentiality_level,
        ai_access_level=asset.ai_access_level,
        asset_status=asset.asset_status,
        visibility=asset.visibility,
        tags=[t.tag_name for t in asset.tags],
        summary_text=summary_text,
        project_name=projects.get(asset.project_id) if asset.project_id else None,
        lifecycle_phase=asset.lifecycle_phase_key,
        confidence=None,
        last_called_at=asset.last_called_at,
        updated_at=asset.updated_at,
        access_info=access,
        index_status=ver.index_status if ver else None,
        weknora_parse_status=ver.weknora_parse_status if ver else None,
        index_error_message=_index_user_message(ver),
        indexed_at=ver.indexed_at if ver else None,
    )


def _like_pattern(keyword: str) -> str:
    escaped = keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def _list_summary_maps(
    session: AsyncSession, assets: list[KnowledgeAsset]
) -> dict[uuid.UUID, dict[str, str | None]]:
    """Load only summary variants safe for each page asset."""
    asset_ids = [asset.id for asset in assets]
    if not asset_ids:
        return {}
    rows = (
        await session.execute(
            select(
                KnowledgeAssetSummary.asset_id,
                KnowledgeAssetSummary.summary_type,
                KnowledgeAssetSummary.content,
            )
            .join(KnowledgeAsset, KnowledgeAsset.id == KnowledgeAssetSummary.asset_id)
            .where(
                KnowledgeAssetSummary.asset_id.in_(asset_ids),
                or_(
                    and_(
                        KnowledgeAsset.confidentiality_level.in_(_REDACTED_LEVELS),
                        KnowledgeAssetSummary.summary_type.in_(
                            ["redacted_summary", "safe_summary"]
                        ),
                    ),
                    and_(
                        KnowledgeAsset.confidentiality_level.notin_(_REDACTED_LEVELS),
                        KnowledgeAssetSummary.summary_type.in_(["one_liner", "detailed"]),
                    ),
                ),
            )
        )
    ).all()
    result: dict[uuid.UUID, dict[str, str | None]] = {}
    for asset_id, summary_type, content in rows:
        result.setdefault(asset_id, {})[summary_type] = content
    return result


async def list_knowledge(
    session: AsyncSession,
    caller: CallerContext,
    *,
    scope: str | None = None,
    project_id: uuid.UUID | None = None,
    include_archived: bool = False,
    keyword: str | None = None,
    zone: str | None = None,
    asset_type: str | None = None,
    asset_status: str | None = None,
    confidentiality_level: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    updated_from: datetime | None = None,
    updated_to: datetime | None = None,
    sort_by: str = "updated_at",
    sort_direction: str = "desc",
    page: int = 1,
    page_size: int = 50,
) -> KnowledgeListResponse:
    """Return a permission-filtered, stable page of discoverable assets."""
    # include_archived is retained for legacy clients; discovery policy still excludes archived assets.
    if project_id is not None:
        if scope not in {None, KnowledgeScope.project.value}:
            raise _denied(422, "project_filter_scope_mismatch", "项目筛选仅适用于项目知识")
        if project_id not in caller.active_project_ids:
            raise _denied(403, "project_membership_required", "需为该项目的有效成员")

    conditions = [discovery_filter(caller)]
    if scope:
        conditions.append(KnowledgeAsset.scope == scope)
    if project_id is not None:
        conditions.append(KnowledgeAsset.project_id == project_id)
    if zone:
        conditions.append(KnowledgeAsset.zone == zone)
    if asset_type:
        conditions.append(KnowledgeAsset.asset_type == asset_type)
    if asset_status:
        conditions.append(KnowledgeAsset.asset_status == asset_status)
    if confidentiality_level:
        conditions.append(KnowledgeAsset.confidentiality_level == confidentiality_level)
    if created_from:
        conditions.append(KnowledgeAsset.created_at >= created_from)
    if created_to:
        conditions.append(KnowledgeAsset.created_at <= created_to)
    if updated_from:
        conditions.append(KnowledgeAsset.updated_at >= updated_from)
    if updated_to:
        conditions.append(KnowledgeAsset.updated_at <= updated_to)
    if keyword:
        pattern = _like_pattern(keyword)
        conditions.append(
            or_(
                KnowledgeAsset.title.ilike(pattern, escape="\\"),
                KnowledgeAsset.tags.any(KnowledgeAssetTag.tag_name.ilike(pattern, escape="\\")),
            )
        )

    total = int(
        (
            await session.execute(
                select(func.count()).select_from(KnowledgeAsset).where(*conditions)
            )
        ).scalar_one()
    )
    sort_columns = {
        "updated_at": KnowledgeAsset.updated_at,
        "created_at": KnowledgeAsset.created_at,
        "title": func.lower(KnowledgeAsset.title),
        "confidentiality_level": KnowledgeAsset.confidentiality_level,
        "asset_status": KnowledgeAsset.asset_status,
    }
    primary = sort_columns[sort_by]
    order = primary.asc() if sort_direction == "asc" else primary.desc()
    tie_breaker = KnowledgeAsset.id.asc() if sort_direction == "asc" else KnowledgeAsset.id.desc()
    stmt = (
        select(KnowledgeAsset)
        .where(*conditions)
        .options(selectinload(KnowledgeAsset.tags))
        .order_by(order, tie_breaker)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    assets = list((await session.execute(stmt)).scalars().all())

    policy = await load_access_policy(session)
    visible = [a for a in assets if decide(caller, a, AccessLayer.discovery, policy=policy).allowed]
    projects, _users = await _aux_maps(session, visible)
    granted = await original_access.active_grant_asset_ids(session, caller, [a.id for a in visible])
    vindex = await _version_index_map(session, visible)
    summary_maps = await _list_summary_maps(session, visible)
    items = [
        _to_list_item(
            caller,
            asset,
            projects,
            granted,
            vindex,
            policy,
            summary_maps.get(asset.id, {}),
        )
        for asset in visible
    ]
    return KnowledgeListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_next=page * page_size < total,
    )


async def get_detail(
    session: AsyncSession, caller: CallerContext, asset_id: uuid.UUID
) -> KnowledgeDetailOut:
    """知识详情：discovery 被拒按安全口径处理（l5/personal/archived → 404）。"""
    asset = (
        await session.execute(
            select(KnowledgeAsset)
            .where(KnowledgeAsset.id == asset_id)
            .options(
                selectinload(KnowledgeAsset.tags),
                selectinload(KnowledgeAsset.summaries),
            )
        )
    ).scalar_one_or_none()

    not_found = _denied(404, "knowledge_asset_not_found", "知识资产不存在或不可见")
    if asset is None:
        raise not_found

    policy = await load_access_policy(session)
    d = decide(caller, asset, AccessLayer.discovery, policy=policy)
    if not d.allowed:
        if d.denied_reason == DeniedReason.user_inactive:
            raise _denied(403, DeniedReason.user_inactive.value, "用户已停用")
        # l5_not_discoverable / personal_asset_not_owned / asset_not_active 一律表现为不存在。
        raise not_found

    # 当前版本（含安全索引状态字段，）。先取出供 access_info 计算 can_retry_index。
    version_obj: KnowledgeAssetVersion | None = None
    if asset.current_version_id:
        version_obj = (
            await session.execute(
                select(KnowledgeAssetVersion).where(
                    KnowledgeAssetVersion.id == asset.current_version_id
                )
            )
        ).scalar_one_or_none()

    # 原文层叠加 active access_grant + 标注当前是否有 pending 原文申请。
    has_grant, grant_expires_at, pending_request = await original_access.detail_access_state(
        session, caller, asset.id
    )
    access = _build_access_info(
        caller,
        asset,
        has_grant=has_grant,
        grant_expires_at=grant_expires_at,
        pending_request=pending_request,
        index_status=version_obj.index_status if version_obj else None,
        policy=policy,
    )
    smap = _summary_map(asset)

    # 摘要对象仅在 summary 层允许时构建。
    summary_obj: SummaryOut | None = None
    if access.summary:
        if asset.confidentiality_level in _REDACTED_LEVELS:
            safe = smap.get("redacted_summary") or smap.get("safe_summary")
            summary_obj = SummaryOut(one_liner=safe, detailed=safe, key_points=[])
        else:
            kp_raw = smap.get("key_points")
            key_points = (
                [line.strip() for line in kp_raw.split("\n") if line.strip()] if kp_raw else []
            )
            summary_obj = SummaryOut(
                one_liner=smap.get("one_liner"),
                detailed=smap.get("detailed"),
                key_points=key_points,
            )

    # 当前版本信息（仅元数据，不含原文内容）。复用上面已加载的 version_obj。
    current_version: CurrentVersionOut | None = None
    if version_obj is not None:
        current_version = CurrentVersionOut(
            id=version_obj.id,
            version_no=version_obj.version_no,
            version_status=version_obj.version_status,
        )

    projects, users = await _aux_maps(session, [asset])
    maintainer: MaintainerOut | None = None
    if asset.maintainer_user_id and asset.maintainer_user_id in users:
        maintainer = MaintainerOut(
            id=asset.maintainer_user_id, name=users[asset.maintainer_user_id]
        )

    return KnowledgeDetailOut(
        id=asset.id,
        title=asset.title,
        scope=asset.scope,
        zone=asset.zone,
        asset_type=asset.asset_type,
        confidentiality_level=asset.confidentiality_level,
        ai_access_level=asset.ai_access_level,
        asset_status=asset.asset_status,
        visibility=asset.visibility,
        tags=[t.tag_name for t in asset.tags],
        project_id=asset.project_id,
        project_name=projects.get(asset.project_id) if asset.project_id else None,
        lifecycle_phase=asset.lifecycle_phase_key,
        maintainer=maintainer,
        confidence=None,
        last_called_at=asset.last_called_at,
        updated_at=asset.updated_at,
        archived_at=asset.archived_at,
        archive_reason=asset.archive_reason,
        summary=summary_obj,
        current_version=current_version,
        access_info=access,
        index_status=version_obj.index_status if version_obj else None,
        weknora_parse_status=version_obj.weknora_parse_status if version_obj else None,
        # 安全目录 code：历史脏 code 也归一，不外显原始上游 code。
        index_error_code=(
            error_catalog.safe_code(version_obj.index_error_code)
            if (version_obj and version_obj.index_status == "index_failed")
            else None
        ),
        index_error_message=_index_user_message(version_obj),
        indexed_at=version_obj.indexed_at if version_obj else None,
    )


async def list_my_knowledge(
    session: AsyncSession, caller: CallerContext
) -> list[KnowledgeListItemOut]:
    """个人知识：仅返回本人的 scope=personal 资产；纯 admin 返回 403。"""
    if not caller.is_business_user:
        # admin 不作为业务个人知识库主体。
        raise _denied(
            403,
            "admin_business_permission_denied",
            "仅业务用户可拥有个人知识库",
        )
    stmt = (
        select(KnowledgeAsset)
        .where(
            KnowledgeAsset.scope == KnowledgeScope.personal.value,
            KnowledgeAsset.owner_user_id == caller.user_id,
        )
        .options(selectinload(KnowledgeAsset.tags), selectinload(KnowledgeAsset.summaries))
    )
    assets = list((await session.execute(stmt)).scalars().all())
    # 复用 discovery 决策过滤：与权限口径一致，本人 archived/deprecated personal
    # 资产默认不进入个人知识列表（读侧默认过滤），而非只写 SQL 状态条件。
    policy = await load_access_policy(session)
    visible = [a for a in assets if decide(caller, a, AccessLayer.discovery, policy=policy).allowed]
    projects, _users = await _aux_maps(session, visible)
    granted = await original_access.active_grant_asset_ids(session, caller, [a.id for a in visible])
    vindex = await _version_index_map(session, visible)
    return [_to_list_item(caller, a, projects, granted, vindex, policy) for a in visible]


async def delete_asset(
    session: AsyncSession,
    caller: CallerContext,
    asset_id: uuid.UUID,
    *,
    reason: str | None,
    weknora: WeKnoraClient | NullWeKnoraClient,
    trace_id: str,
) -> KnowledgeDeleteResponse:
    """受控删除 / 撤下。

    置 asset_status=deleted（不物理删行），撤销 active access_grants、取消 pending 原文申请，
    并尽力删除 WeKnora 索引；平台权限层立即 fail-closed（资产退出列表/检索/问答/预览/Agent/
    原文授权运行时）。无权时按安全口径处理：不可发现 → 404（不泄露存在性），可发现但无删除权 → 403。
    """
    asset = (
        await session.execute(
            select(KnowledgeAsset)
            .where(KnowledgeAsset.id == asset_id)
            .options(selectinload(KnowledgeAsset.tags))
        )
    ).scalar_one_or_none()

    not_found = _denied(404, "knowledge_asset_not_found", "知识资产不存在或不可见")
    if asset is None or asset.asset_status == _DELETED_STATUS:
        raise not_found

    if not _can_delete(caller, asset):
        # 不可发现（他人 personal / 不可发现 L5）→ 404 不泄露；可发现但无删除权 → 403。
        discoverable = decide(caller, asset, AccessLayer.discovery).allowed
        if not discoverable:
            raise not_found
        if not caller.is_business_user:
            raise _denied(403, "admin_business_permission_denied", "系统管理员不具备业务知识删除权")
        raise _denied(403, "knowledge_delete_forbidden", "无权删除该知识资产")

    prev_status = asset.asset_status
    clean_reason = (reason or "").strip()[:500] or None

    # 1) 撤销与该资产相关的 active access_grants（运行时立即失效）。
    grants = list(
        (
            await session.execute(
                select(AccessGrant).where(
                    AccessGrant.asset_id == asset_id, AccessGrant.status == "active"
                )
            )
        )
        .scalars()
        .all()
    )
    for g in grants:
        g.status = "revoked"
        g.revoked_at = utc_now()
        g.revoked_by_user_id = caller.user_id
        g.revoke_reason = "asset_deleted"

    # 2) 取消该资产的 pending 原文申请（避免 UI 仍显示可审批）。
    pendings = list(
        (
            await session.execute(
                select(OriginalAccessRequest).where(
                    OriginalAccessRequest.asset_id == asset_id,
                    OriginalAccessRequest.status == "pending",
                )
            )
        )
        .scalars()
        .all()
    )
    for r in pendings:
        r.status = "cancelled"
        r.reviewer_user_id = caller.user_id
        r.reviewed_at = utc_now()
        r.review_note = "asset_deleted"

    # 3) 尽力删除 WeKnora 索引（active 版本 doc）。失败不阻断软删除——平台层已 fail-closed。
    weknora_attempted = False
    weknora_succeeded = False
    if weknora_enabled():
        version = (
            await session.execute(
                select(KnowledgeAssetVersion)
                .where(KnowledgeAssetVersion.asset_id == asset_id)
                .where(KnowledgeAssetVersion.version_status == "active")
            )
        ).scalar_one_or_none()
        doc_id = version.weknora_doc_id if version is not None else None
        # doc_id 非空 ⟹ version 非 None（上一行由其推导）；显式并入条件以收敛类型且行为不变。
        if version is not None and doc_id:
            weknora_attempted = True
            try:
                await weknora.delete_knowledge(doc_id, trace_id=trace_id)
                weknora_succeeded = True
                version.weknora_parse_status = "deleted"
            except Exception as exc:  # noqa: BLE001
                safe_log_exception(
                    _logger,
                    "weknora_delete_cleanup_failed",
                    exc,
                    include_summary=False,
                    level=logging.WARNING,
                )
                # 外部索引清理失败**绝不**阻断平台软删除：WeKnoraError / httpx 网络·超时·
                # 连接错误（HTTPError/RequestError/TimeoutException）/ OSError 等任意异常都吞掉，
                # 资产仍按 deleted fail-closed。只记安全运营标记，不写异常文本 / kb·doc id / URL。
                weknora_succeeded = False

    # 4) 软删除资产（保留行 + 追溯字段）。
    asset.asset_status = _DELETED_STATUS
    asset.deleted_at = utc_now()
    asset.deleted_by = caller.user_id
    asset.delete_reason = clean_reason

    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.knowledge_asset_deleted.value,
        trace_id=trace_id,
        target_type="knowledge_asset",
        target_id=asset.id,
        before={"asset_status": prev_status},
        after={
            "asset_status": asset.asset_status,
            "scope": asset.scope,
            "zone": asset.zone,
            "confidentiality_level": asset.confidentiality_level,
        },
        extra={
            "reason": clean_reason,
            "revoked_grants": len(grants),
            "cancelled_requests": len(pendings),
            "weknora_delete_attempted": weknora_attempted,
            "weknora_delete_succeeded": weknora_succeeded,
        },
        project_id=asset.project_id,
    )
    await session.commit()
    return KnowledgeDeleteResponse(
        asset_id=asset.id,
        asset_status=asset.asset_status,
        deleted_at=asset.deleted_at,
        trace_id=trace_id,
    )


async def _audit_retry_failed(
    session: AsyncSession,
    caller: CallerContext,
    asset_id: uuid.UUID,
    error_code: str | None,
    trace_id: str,
    project_id: uuid.UUID | None,
) -> None:
    """重试后底座仍失败的审计（exception）。extra 只放安全 stage + error_code。"""
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.exception,
        action=AuditAction.knowledge_index_retry_failed.value,
        trace_id=trace_id,
        target_type="knowledge_asset",
        target_id=asset_id,
        severity=AlertSeverity.warning,
        risk_level=AuditRiskLevel.high.value,
        # 审计 extra 只写安全目录 code，不写上游原始 code。
        extra={
            "failure_stage": "weknora_index_retry",
            "error_code": error_catalog.safe_code(error_code),
        },
        project_id=project_id,
    )
    await session.commit()


async def retry_index(
    session: AsyncSession,
    caller: CallerContext,
    asset_id: uuid.UUID,
    *,
    weknora: WeKnoraClient | NullWeKnoraClient,
    storage: LocalFileStorage,
    trace_id: str,
    embedding_model_ref: str | None = None,
    rerank_model_ref: str | None = None,
) -> RetryIndexResponse:
    """对 index_failed / not_indexed / skipped 的资产重试底座索引。

    复用 `indexing.index_asset_version` 与 confirm 同一安全机制：资产已落库，重试只推进底座、
    回写 version 索引状态；失败仍 index_failed（可再试）。权限同 `_can_retry_index`；纯 admin /
    无权者被拒。**绝不**外泄 kb_id / doc_id / api_key / storage_ref / 原文。
    """
    asset = (
        await session.execute(select(KnowledgeAsset).where(KnowledgeAsset.id == asset_id))
    ).scalar_one_or_none()
    not_found = _denied(404, "knowledge_asset_not_found", "知识资产不存在或不可见")
    if asset is None or asset.asset_status == _DELETED_STATUS:
        raise not_found
    if not can_retry_index(caller, asset):
        # 不可发现 → 404 不泄露；可发现但无重试权 → 403（纯 admin 单独提示）。
        if not decide(caller, asset, AccessLayer.discovery).allowed:
            raise not_found
        if not caller.is_business_user:
            raise _denied(403, "admin_business_permission_denied", "系统管理员不具备业务索引重试权")
        raise _denied(403, "knowledge_index_retry_forbidden", "无权重试该资产的底座索引")

    version = (
        await session.execute(
            select(KnowledgeAssetVersion)
            .where(KnowledgeAssetVersion.asset_id == asset_id)
            .where(KnowledgeAssetVersion.version_status == "active")
        )
    ).scalar_one_or_none()
    if version is None:
        raise _denied(409, "knowledge_index_no_active_version", "资产无 active 版本，无法重试索引")
    if version.index_status == "indexed":
        raise _denied(409, "knowledge_index_already_indexed", "该资产已索引，无需重试")
    if version.index_status not in _RETRYABLE_INDEX_STATUSES:
        # 例如 indexing 进行中：不重复触发。
        raise _denied(409, "knowledge_index_not_retryable", "当前索引状态不可重试")

    # 捕获安全字段（后续 index_asset_version 失败路径 rollback 会使 ORM 对象过期）。
    version_id = version.id
    scope = asset.scope
    owner_user_id = asset.owner_user_id
    confidentiality = asset.confidentiality_level
    project_id = asset.project_id
    from_status = version.index_status

    # 发起审计（operation）。
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.knowledge_index_retry_requested.value,
        trace_id=trace_id,
        target_type="knowledge_asset",
        target_id=asset_id,
        extra={"scope": scope, "from_index_status": from_status},
        project_id=project_id,
    )
    await session.commit()

    # 底座未配置：标 skipped 返回（不伪装 indexed，不写失败审计）。
    # 清理上一轮失败残留：避免"已跳过索引"还混搭旧 index_error_* / parse=failed 的脏状态。
    if not weknora_enabled():
        v = (
            await session.execute(
                select(KnowledgeAssetVersion).where(KnowledgeAssetVersion.id == version_id)
            )
        ).scalar_one_or_none()
        if v is not None:
            v.index_status = "skipped"
            v.index_error_code = None
            v.index_error_message = None
            # 底座未启用的 skipped 不应保留旧解析失败态（skipped 表示"未推进底座"，无解析进度可言）。
            v.weknora_parse_status = None
        await session.commit()
        return RetryIndexResponse(
            asset_id=asset_id,
            index_status="skipped",
            weknora_parse_status=None,
            index_error_code=None,
            index_error_message=None,
            trace_id=trace_id,
        )

    # 取入库任务的 server-only source_file_ref（只读取 ref，不外泄）。
    task = (
        (
            await session.execute(
                select(IngestTask)
                .where(IngestTask.result_asset_id == asset_id)
                .order_by(IngestTask.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    if task is None or not task.source_file_ref:
        raise _denied(
            409,
            "knowledge_index_source_unavailable",
            "找不到原文来源，无法重传底座（可能为历史数据）",
        )
    source_file_name = task.source_file_name
    source_file_mime = task.source_file_mime_type
    channel = task.source

    # 读原文字节：读盘失败也算索引失败（资产保留、可再试）。
    try:
        file_bytes = storage.resolve_path(task.source_file_ref).read_bytes()
    except OSError:
        outcome = await indexing.mark_index_failed(
            session, version_id=version_id, error_code="source_file_unreadable"
        )
        await _audit_retry_failed(
            session, caller, asset_id, outcome.error_code, trace_id, project_id
        )
        return await _retry_response(session, asset_id, version_id, outcome, trace_id)

    outcome = await indexing.index_asset_version(
        session,
        weknora,
        asset_id=asset_id,
        version_id=version_id,
        scope=scope,
        owner_user_id=owner_user_id,
        project_id=project_id,
        confidentiality=confidentiality,
        file_bytes=file_bytes,
        source_file_name=source_file_name,
        source_file_mime=source_file_mime,
        channel=channel,
        trace_id=trace_id,
        embedding_model_ref=embedding_model_ref,
        rerank_model_ref=rerank_model_ref,
    )
    if outcome.index_status == "indexed":
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.knowledge_index_retried.value,
            trace_id=trace_id,
            target_type="knowledge_asset",
            target_id=asset_id,
            extra={
                "scope": scope,
                "parse_status": outcome.parse_status,
                "is_duplicate": outcome.is_duplicate,
            },
            project_id=project_id,
        )
        await session.commit()
    else:
        await _audit_retry_failed(
            session, caller, asset_id, outcome.error_code, trace_id, project_id
        )
    return await _retry_response(session, asset_id, version_id, outcome, trace_id)


async def _retry_response(
    session: AsyncSession,
    asset_id: uuid.UUID,
    version_id: uuid.UUID,
    outcome: indexing.IndexOutcome,
    trace_id: str,
) -> RetryIndexResponse:
    """从 outcome + 最新 version 状态构建安全重试响应（不含 kb/doc id）。"""
    v = (
        await session.execute(
            select(KnowledgeAssetVersion).where(KnowledgeAssetVersion.id == version_id)
        )
    ).scalar_one_or_none()
    safe = error_catalog.safe_code(outcome.error_code) if outcome.error_code else None
    return RetryIndexResponse(
        asset_id=asset_id,
        index_status=outcome.index_status,
        weknora_parse_status=outcome.parse_status or (v.weknora_parse_status if v else None),
        # 安全目录 code：不外显上游原始 code。
        index_error_code=safe if outcome.index_status == "index_failed" else None,
        # 用户态文案按当前目录派生，不外显历史 / 上游脏文案。
        index_error_message=(
            error_catalog.user_message(safe) if outcome.index_status == "index_failed" else None
        ),
        trace_id=trace_id,
    )

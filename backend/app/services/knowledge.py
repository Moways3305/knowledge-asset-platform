"""Knowledge 读服务（IMPLEMENT-04）。

组织列表 / 详情 / 个人知识三类只读能力。所有 discovery / summary / original
判断**必须**调用 `app.services.permission`，不在此重写权限矩阵。

过渡策略说明：
- 当前 summaries 为窄表（summary_type + content）。L3/L4 摘要使用
  `redacted_summary` / `safe_summary` 行作为安全摘要；若 seed 未提供，则回退
  为 None（不暴露普通摘要）。这是 IMPLEMENT-04 的过渡口径。
- `confidence` 未在 knowledge_assets 落地（见 IMPLEMENT-02 差异），统一返回 None。
- include_archived=true 当前不额外放行归档资产：权限服务对 archived/deprecated
  作 asset_not_active 处理（发现层拒绝），治理归档视图留待 IMPLEMENT-10。
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from datetime import datetime, timezone

from app.models.identity import Project, User
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.original_access import AccessGrant, OriginalAccessRequest
from app.schemas.enums import (
    AssetStatus,
    AuditAction,
    AuditLogType,
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
    MaintainerOut,
    SummaryOut,
)
from app.schemas.permission import (
    AccessLayer,
    CallerContext,
    DeniedReason,
)
from app.services.permission import decide
from app.services import audit as audit_service
from app.services import original_access
from app.services.weknora_client import (
    NullWeKnoraClient,
    WeKnoraClient,
    weknora_enabled,
)

_INACTIVE_STATUSES = [AssetStatus.archived.value, AssetStatus.deprecated.value]
_DELETED_STATUS = AssetStatus.deleted.value
_REDACTED_LEVELS = {ConfidentialityLevel.L3.value, ConfidentialityLevel.L4.value}


def _can_delete(caller: CallerContext, asset: KnowledgeAsset) -> bool:
    """受控删除权限（PBC-10B，后端权威）。

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
) -> AccessInfoOut:
    """基于权限服务的三层决策构建 access_info（PBC-06：原文层叠加 active access_grant）。"""
    o = decide(caller, asset, AccessLayer.original, has_original_grant=has_grant)
    d = decide(caller, asset, AccessLayer.discovery, has_original_grant=has_grant)
    s = decide(caller, asset, AccessLayer.summary, has_original_grant=has_grant)
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
            await session.execute(
                select(User.id, User.name).where(User.id.in_(user_ids))
            )
        ).all()
        users = {r[0]: r[1] for r in rows}
    return projects, users


def _to_list_item(
    caller: CallerContext,
    asset: KnowledgeAsset,
    projects: dict[uuid.UUID, str],
    granted_ids: set[uuid.UUID] | None = None,
) -> KnowledgeListItemOut:
    access = _build_access_info(caller, asset, has_grant=bool(granted_ids and asset.id in granted_ids))
    smap = _summary_map(asset)
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
    )


async def list_knowledge(
    session: AsyncSession,
    caller: CallerContext,
    *,
    scope: str | None = None,
    include_archived: bool = False,
) -> list[KnowledgeListItemOut]:
    """知识列表：只返回调用人可发现的资产。"""
    stmt = select(KnowledgeAsset).options(
        selectinload(KnowledgeAsset.tags), selectinload(KnowledgeAsset.summaries)
    )
    if scope:
        stmt = stmt.where(KnowledgeAsset.scope == scope)
    # deleted（PBC-10B）始终排除，即使 include_archived（删除 ≠ 归档；decide() 也会拦截，此处双保险）。
    stmt = stmt.where(KnowledgeAsset.asset_status != _DELETED_STATUS)
    if not include_archived:
        stmt = stmt.where(KnowledgeAsset.asset_status.notin_(_INACTIVE_STATUSES))

    assets = list((await session.execute(stmt)).scalars().all())
    # 发现层过滤：不可发现的资产（他人 personal、无权 L5、archived 等）直接剔除。
    visible = [a for a in assets if decide(caller, a, AccessLayer.discovery).allowed]
    projects, _users = await _aux_maps(session, visible)
    granted = await original_access.active_grant_asset_ids(session, caller, [a.id for a in visible])
    return [_to_list_item(caller, a, projects, granted) for a in visible]


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

    d = decide(caller, asset, AccessLayer.discovery)
    if not d.allowed:
        if d.denied_reason == DeniedReason.user_inactive:
            raise _denied(403, DeniedReason.user_inactive.value, "用户已停用")
        # l5_not_discoverable / personal_asset_not_owned / asset_not_active 一律表现为不存在。
        raise not_found

    # PBC-06：原文层叠加 active access_grant + 标注当前是否有 pending 原文申请。
    has_grant, grant_expires_at, pending_request = await original_access.detail_access_state(
        session, caller, asset.id
    )
    access = _build_access_info(
        caller, asset, has_grant=has_grant,
        grant_expires_at=grant_expires_at, pending_request=pending_request,
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
                [line.strip() for line in kp_raw.split("\n") if line.strip()]
                if kp_raw
                else []
            )
            summary_obj = SummaryOut(
                one_liner=smap.get("one_liner"),
                detailed=smap.get("detailed"),
                key_points=key_points,
            )

    # 当前版本信息（仅元数据，不含原文内容）。
    current_version: CurrentVersionOut | None = None
    if asset.current_version_id:
        version = (
            await session.execute(
                select(KnowledgeAssetVersion).where(
                    KnowledgeAssetVersion.id == asset.current_version_id
                )
            )
        ).scalar_one_or_none()
        if version is not None:
            current_version = CurrentVersionOut(
                id=version.id,
                version_no=version.version_no,
                version_status=version.version_status,
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
        .options(
            selectinload(KnowledgeAsset.tags), selectinload(KnowledgeAsset.summaries)
        )
    )
    assets = list((await session.execute(stmt)).scalars().all())
    # 复用 discovery 决策过滤：与权限口径一致，本人 archived/deprecated personal
    # 资产默认不进入个人知识列表（读侧默认过滤），而非只写 SQL 状态条件。
    visible = [a for a in assets if decide(caller, a, AccessLayer.discovery).allowed]
    projects, _users = await _aux_maps(session, visible)
    granted = await original_access.active_grant_asset_ids(session, caller, [a.id for a in visible])
    return [_to_list_item(caller, a, projects, granted) for a in visible]


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def delete_asset(
    session: AsyncSession,
    caller: CallerContext,
    asset_id: uuid.UUID,
    *,
    reason: str | None,
    weknora: "WeKnoraClient | NullWeKnoraClient",
    trace_id: str,
) -> KnowledgeDeleteResponse:
    """受控删除 / 撤下（PBC-10B，软删除）。

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
        ).scalars().all()
    )
    for g in grants:
        g.status = "revoked"
        g.revoked_at = _now()
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
        ).scalars().all()
    )
    for r in pendings:
        r.status = "cancelled"
        r.reviewer_user_id = caller.user_id
        r.reviewed_at = _now()
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
        if doc_id:
            weknora_attempted = True
            try:
                await weknora.delete_knowledge(doc_id, trace_id=trace_id)
                weknora_succeeded = True
                version.weknora_parse_status = "deleted"
            except Exception:  # noqa: BLE001
                # 外部索引清理失败**绝不**阻断平台软删除：WeKnoraError / httpx 网络·超时·
                # 连接错误（HTTPError/RequestError/TimeoutException）/ OSError 等任意异常都吞掉，
                # 资产仍按 deleted fail-closed。只记安全运营标记，不写异常文本 / kb·doc id / URL。
                weknora_succeeded = False

    # 4) 软删除资产（保留行 + 追溯字段）。
    asset.asset_status = _DELETED_STATUS
    asset.deleted_at = _now()
    asset.deleted_by = caller.user_id
    asset.delete_reason = clean_reason

    await audit_service.record_event(
        session, caller=caller, log_type=AuditLogType.operation,
        action=AuditAction.knowledge_asset_deleted.value, trace_id=trace_id,
        target_type="knowledge_asset", target_id=asset.id,
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
        asset_id=asset.id, asset_status=asset.asset_status,
        deleted_at=asset.deleted_at, trace_id=trace_id,
    )

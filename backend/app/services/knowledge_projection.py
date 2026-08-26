"""Knowledge access decisions, safe summaries, and response projection helpers."""

from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Project, User
from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetSummary,
    KnowledgeAssetVersion,
)
from app.schemas.enums import (
    AssetStatus,
    ConfidentialityLevel,
    KnowledgeScope,
    ProjectRole,
)
from app.schemas.knowledge import (
    AccessInfoOut,
    KnowledgeListItemOut,
)
from app.schemas.permission import (
    DEFAULT_POLICY,
    AccessLayer,
    CallerContext,
    DefaultAccessPolicy,
    DeniedReason,
)
from app.services import (
    error_catalog,
    knowledge_lifecycle,
)
from app.services.permission import (
    decide,
    lifecycle_actor_allowed,
    lifecycle_visibility,
)

_logger = logging.getLogger(__name__)

_INACTIVE_STATUSES = ["processing", AssetStatus.archived.value, AssetStatus.deprecated.value]
_DELETED_STATUS = AssetStatus.deleted.value
_REDACTED_LEVELS = {ConfidentialityLevel.L3.value, ConfidentialityLevel.L4.value}


_can_delete = knowledge_lifecycle.can_delete


_RETRYABLE_INDEX_STATUSES = {"index_failed", "not_indexed", "skipped"}


def _index_user_message(ver) -> str | None:
    """index_failed 版本的用户态安全文案——始终按当前目录从 index_error_code 重新派生，
    避免历史 DB 里的旧 / 脏文案继续外显。其它状态返回 None。"""
    if ver is None or ver.index_status != "index_failed":
        return None
    return error_catalog.user_message(ver.index_error_code)


_INACTIVE_STATUSES = ["processing", AssetStatus.archived.value, AssetStatus.deprecated.value]
_DELETED_STATUS = AssetStatus.deleted.value
_REDACTED_LEVELS = {ConfidentialityLevel.L3.value, ConfidentialityLevel.L4.value}


_can_delete = knowledge_lifecycle.can_delete


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
    """把当前版本 summaries（窄表）整理为 {summary_type: content}。"""
    if asset.current_version_id is None:
        return {}
    return {
        summary.summary_type: summary.content
        for summary in asset.summaries
        if summary.version_id == asset.current_version_id
    }


def _select_summary_text(level: str, smap: dict[str, str | None]) -> str | None:
    """列表用的单段摘要文本（按保密级别选择安全摘要）。"""
    if level in _REDACTED_LEVELS:
        full = smap.get("redacted_summary") or smap.get("safe_summary")
        return smap.get("redacted_one_liner") or (full[:200] if full else None)
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
    cross_project_summary = (
        asset.scope == KnowledgeScope.project.value
        and asset.project_id not in caller.active_project_ids
    )
    return AccessInfoOut(
        discovery=d.allowed,
        summary=s.allowed,
        original=o.allowed,
        effective_source=source,
        can_request_original=can_request,
        cross_project_summary=cross_project_summary,
        existing_request_status="pending" if pending_request else None,
        existing_grant_expires_at=grant_expires_at if has_grant else None,
        can_delete=_can_delete(caller, asset),
        can_manage_lifecycle=(
            caller.is_business_user
            and lifecycle_visibility(caller, asset) is None
            and lifecycle_actor_allowed(caller, asset)
        ),
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
    # 原文 grant 只提升独立原文端点的读取权限，不能解除列表的跨项目安全投影。
    cross_project_projection = access.cross_project_summary
    return KnowledgeListItemOut(
        id=asset.id,
        title=asset.title,
        canonical_name=None if cross_project_projection else asset.canonical_name,
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
        lifecycle_phase=None if cross_project_projection else asset.lifecycle_phase_key,
        confidence=None,
        last_called_at=None if cross_project_projection else asset.last_called_at,
        updated_at=asset.updated_at,
        access_info=access,
        index_status=None if cross_project_projection else ver.index_status if ver else None,
        weknora_parse_status=(
            None if cross_project_projection else ver.weknora_parse_status if ver else None
        ),
        index_error_message=None if cross_project_projection else _index_user_message(ver),
        indexed_at=None if cross_project_projection else ver.indexed_at if ver else None,
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
                KnowledgeAssetSummary.version_id == KnowledgeAsset.current_version_id,
                or_(
                    and_(
                        KnowledgeAsset.confidentiality_level.in_(_REDACTED_LEVELS),
                        KnowledgeAssetSummary.summary_type.in_(
                            ["redacted_one_liner", "redacted_summary", "safe_summary"]
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

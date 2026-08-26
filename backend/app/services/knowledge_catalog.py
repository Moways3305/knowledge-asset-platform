"""Cross-scope knowledge catalog, directory, project, and detail queries."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetFileObject,
    KnowledgeAssetTag,
    KnowledgeAssetVersion,
)
from app.schemas.enums import (
    KnowledgeScope,
    PersonalKnowledgeState,
    ReviewTaskStatus,
)
from app.schemas.knowledge import (
    CurrentVersionOut,
    DirectoryListResponse,
    DirectoryOut,
    KnowledgeDetailOut,
    KnowledgeLibraryProjectListResponse,
    KnowledgeLibraryProjectOut,
    KnowledgeListResponse,
    MaintainerOut,
    SummaryOut,
)
from app.schemas.permission import (
    AccessLayer,
    CallerContext,
    DeniedReason,
)
from app.services import (
    directories,
    discoverable_projects,
    error_catalog,
    original_access,
)
from app.services.knowledge_projection import (
    _REDACTED_LEVELS,
    _aux_maps,
    _build_access_info,
    _denied,
    _index_user_message,
    _like_pattern,
    _list_summary_maps,
    _summary_map,
    _to_list_item,
    _version_index_map,
)
from app.services.permission import (
    decide,
    discovery_filter,
)
from app.services.permission_rules import load_access_policy


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
    directory_key: str | None = None,
    include_descendants: bool = False,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    updated_from: datetime | None = None,
    updated_to: datetime | None = None,
    sort_by: str = "updated_at",
    sort_direction: str = "desc",
    page: int = 1,
    page_size: int = 50,
    require_directory_context: bool = True,
) -> KnowledgeListResponse:
    """Return a permission-filtered, stable page of discoverable assets."""
    # include_archived is retained for legacy clients; discovery policy still excludes archived assets.
    if project_id is not None:
        if scope not in {None, KnowledgeScope.project.value}:
            raise _denied(422, "project_filter_scope_mismatch", "项目筛选仅适用于项目知识")
        if not require_directory_context and project_id not in caller.active_project_ids:
            raise _denied(403, "project_membership_required", "需为该项目的有效成员")

    if require_directory_context and not directory_key:
        raise _denied(
            422,
            "directory_context_required",
            "知识目录列表必须指定正式目录上下文",
        )

    if (
        require_directory_context
        and scope == KnowledgeScope.project.value
        and project_id is not None
        and await discoverable_projects.get_knowledge_library_project(session, caller, project_id)
        is None
    ):
        raise _denied(404, "directory_not_found", "目录不存在或当前不可进入")

    if directory_key:
        if scope is None:
            raise _denied(
                422,
                "directory_scope_required",
                "目录筛选必须明确指定知识范围",
            )
        await directories.validate_directory(
            session,
            directory_key=directory_key,
            scope=scope,
            project_id=project_id,
        )

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
    if directory_key:
        directory_condition = (
            KnowledgeAssetVersion.directory_key.is_(None)
            if directory_key == directories.UNCLASSIFIED_PROJECT_DIRECTORY_KEY
            else KnowledgeAssetVersion.directory_key == directory_key
        )
        conditions.append(
            KnowledgeAsset.current_version_id.in_(
                select(KnowledgeAssetVersion.id).where(directory_condition)
            )
        )
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
    items = []
    for asset in visible:
        item = _to_list_item(
            caller,
            asset,
            projects,
            granted,
            vindex,
            policy,
            summary_maps.get(asset.id, {}),
        )
        version = vindex.get(asset.current_version_id) if asset.current_version_id else None
        key = directories.version_directory_key(version)
        path = await directories.display_path(session, key, asset.project_id)
        items.append(item.model_copy(update={"directory_key": key, "directory_path": path}))
    return KnowledgeListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_next=page * page_size < total,
    )


async def list_directories(
    session: AsyncSession,
    caller: CallerContext,
    *,
    scope: str | None = None,
    project_id: uuid.UUID | None = None,
) -> DirectoryListResponse:
    rows = await directories.visible_directory_rows(
        session,
        caller,
        allowed_scope=scope,
        allowed_project_id=project_id,
    )
    if project_id is not None and not rows:
        # Do not distinguish a missing project from a project with no
        # discoverable assets for this caller.
        raise _denied(404, "directory_not_found", "目录不存在或当前不可进入")
    return DirectoryListResponse(items=[DirectoryOut(**row) for row in rows])


async def list_knowledge_library_projects(
    session: AsyncSession,
    caller: CallerContext,
) -> KnowledgeLibraryProjectListResponse:
    rows = await discoverable_projects.list_knowledge_library_projects(session, caller)
    return KnowledgeLibraryProjectListResponse(
        items=[
            KnowledgeLibraryProjectOut(
                project_id=row.project_id,
                name=row.name,
                status=row.status,
                access_mode=row.access_mode,
                access_label=row.access_label,
            )
            for row in rows
        ]
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
    # grant 后仍保持跨项目安全投影；原文只能通过受审计的原文端点读取。
    cross_project_projection = access.cross_project_summary

    # 摘要对象仅在 summary 层允许时构建。
    summary_obj: SummaryOut | None = None
    if access.summary:
        if asset.confidentiality_level in _REDACTED_LEVELS:
            safe_detailed = smap.get("redacted_summary") or smap.get("safe_summary")
            safe_one_liner = smap.get("redacted_one_liner") or (
                safe_detailed[:200] if safe_detailed else None
            )
            summary_obj = SummaryOut(
                one_liner=safe_one_liner,
                detailed=safe_detailed,
                key_points=[],
            )
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
            display_version=(
                version_obj.naming_metadata.get("version")
                if isinstance(version_obj.naming_metadata, dict)
                else None
            ),
        )

    canonical_markdown_status: str | None = None if cross_project_projection else "not_generated"
    if version_obj is not None and not cross_project_projection:
        canonical_exists = await session.scalar(
            select(KnowledgeAssetFileObject.id)
            .where(
                KnowledgeAssetFileObject.asset_id == asset.id,
                KnowledgeAssetFileObject.version_id == version_obj.id,
                KnowledgeAssetFileObject.file_variant == "canonical_markdown",
                KnowledgeAssetFileObject.storage_ref.is_not(None),
                KnowledgeAssetFileObject.file_hash.is_not(None),
            )
            .limit(1)
        )
        if canonical_exists is not None:
            canonical_markdown_status = "generated"

    projects, users = await _aux_maps(session, [asset])
    maintainer_name = (
        users.get(asset.maintainer_user_id) if asset.maintainer_user_id is not None else None
    )
    maintainer: MaintainerOut | None = None
    if (
        not cross_project_projection
        and asset.maintainer_user_id
        and asset.maintainer_user_id in users
    ):
        maintainer = MaintainerOut(
            id=asset.maintainer_user_id, name=users[asset.maintainer_user_id]
        )
    naming_metadata = (
        version_obj.naming_metadata
        if version_obj is not None and isinstance(version_obj.naming_metadata, dict)
        else {}
    )
    category_parts = [
        str(naming_metadata.get(key) or "").strip()
        for key in ("category_primary", "category_secondary")
    ]
    category_path = " / ".join(part for part in category_parts if part) or None
    directory_key = directories.version_directory_key(version_obj)
    directory_path = await directories.display_path(session, directory_key, asset.project_id)
    safe_version = str(naming_metadata.get("version") or "").strip() or None
    retrieval_available = bool(version_obj and version_obj.index_status == "indexed")

    return KnowledgeDetailOut(
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
        project_id=None if cross_project_projection else asset.project_id,
        project_name=projects.get(asset.project_id) if asset.project_id else None,
        lifecycle_phase=None if cross_project_projection else asset.lifecycle_phase_key,
        maintainer=maintainer,
        maintainer_name=maintainer_name,
        category_path=category_path,
        safe_version=safe_version,
        retrieval_available=retrieval_available,
        qa_available=retrieval_available and asset.ai_access_level in {"A2", "A3", "A4"},
        confidence=None,
        last_called_at=None if cross_project_projection else asset.last_called_at,
        updated_at=asset.updated_at,
        archived_at=None if cross_project_projection else asset.archived_at,
        archive_reason=None if cross_project_projection else asset.archive_reason,
        summary=summary_obj,
        current_version=None if cross_project_projection else current_version,
        canonical_markdown_status=canonical_markdown_status,
        access_info=access,
        index_status=(
            None if cross_project_projection else version_obj.index_status if version_obj else None
        ),
        weknora_parse_status=(
            None
            if cross_project_projection
            else version_obj.weknora_parse_status
            if version_obj
            else None
        ),
        # 安全目录 code：历史脏 code 也归一，不外显原始上游 code。
        index_error_code=(
            error_catalog.safe_code(version_obj.index_error_code)
            if (
                not cross_project_projection
                and version_obj
                and version_obj.index_status == "index_failed"
            )
            else None
        ),
        index_error_message=(
            None if cross_project_projection else _index_user_message(version_obj)
        ),
        indexed_at=(
            None if cross_project_projection else version_obj.indexed_at if version_obj else None
        ),
        directory_key=None if cross_project_projection else directory_key,
        directory_path=None if cross_project_projection else directory_path,
    )


_PERSONAL_STATE_LABELS = {
    PersonalKnowledgeState.awaiting_confirmation.value: "待本人确认",
    PersonalKnowledgeState.ready_to_submit.value: "可提交项目",
    PersonalKnowledgeState.pending_project_review.value: "待项目经理审批",
    PersonalKnowledgeState.active_in_project.value: "已进入项目",
    PersonalKnowledgeState.project_rejected.value: "项目未通过",
}
_PENDING_REVIEW_STATUSES = {
    ReviewTaskStatus.pending_evidence.value,
    ReviewTaskStatus.pending_reviewer.value,
    ReviewTaskStatus.approving.value,
    ReviewTaskStatus.approval_failed.value,
}

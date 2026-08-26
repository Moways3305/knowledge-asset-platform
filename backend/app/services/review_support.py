"""Shared review policy, publication rendering, and response projection helpers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetChunk,
    KnowledgeAssetFileObject,
    KnowledgeAssetSummary,
    KnowledgeAssetTag,
    KnowledgeAssetVersion,
)
from app.models.review import (
    CompanyAssetReviewDecision,
    ReviewTask,
)
from app.schemas.enums import (
    CompanyAssetDecision,
    CompanyRole,
    KnowledgeScope,
    ProjectRole,
    ReviewTaskStatus,
    ReviewType,
)
from app.schemas.naming import NamingPreviewRequest
from app.schemas.permission import CallerContext
from app.schemas.review import (
    ReviewListItem,
)
from app.services import governance_policy, naming_rules

_TERMINAL = {ReviewTaskStatus.approved.value, ReviewTaskStatus.rejected.value}
_NON_TERMINAL = {
    ReviewTaskStatus.pending_evidence.value,
    ReviewTaskStatus.pending_reviewer.value,
    ReviewTaskStatus.approving.value,
    ReviewTaskStatus.approval_failed.value,
}

_FORBIDDEN_ATTACHMENT_KEYS = {
    "url",
    "download_url",
    "file_url",
    "path",
    "storage_ref",
    "source_file_ref",
    "bucket",
    "object_key",
    "token",
}
_FORBIDDEN_VALUE_PREFIXES = (
    "http://",
    "https://",
    "file://",
    "s3://",
    "oss://",
    "internal://",
)


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"denied_reason": reason, "message": message}
    )


def _is_admin(caller: CallerContext) -> bool:
    return governance_policy.is_admin(caller)


async def _render_publication_snapshot(
    session: AsyncSession,
    caller: CallerContext,
    asset: KnowledgeAsset,
    *,
    target_scope: KnowledgeScope,
    target_project_id: uuid.UUID | None,
    confidentiality_level,
    naming,
) -> tuple[dict, naming_rules.RenderedNaming]:
    source_version = await session.get(KnowledgeAssetVersion, asset.current_version_id)
    if (
        asset.asset_status != "active"
        or source_version is None
        or source_version.version_status != "active"
    ):
        raise _denied(409, "publication_source_unavailable", "来源资料当前不可用于发布")
    request = NamingPreviewRequest(
        target_scope=target_scope,
        target_project_id=target_project_id,
        confidentiality_level=confidentiality_level,
        naming=naming,
    )
    rendered = await naming_rules.render_asset_publication(session, caller, asset, request)
    snapshot = {
        "source_asset_id": str(asset.id),
        "source_scope": asset.scope,
        "source_project_id": str(asset.project_id) if asset.project_id else None,
        "source_asset_status": asset.asset_status,
        "source_version_id": str(source_version.id),
        "source_version_status": source_version.version_status,
        "target_scope": target_scope.value,
        "target_project_id": str(target_project_id) if target_project_id else None,
        "confidentiality_level": confidentiality_level.value,
        "naming": naming.model_dump(mode="json"),
        "naming_rule_version": rendered.rule_version,
        "canonical_name": rendered.canonical_name,
    }
    return snapshot, rendered


async def _validate_locked_publication_source(
    session: AsyncSession,
    source: KnowledgeAsset,
    task: ReviewTask,
) -> KnowledgeAssetVersion:
    """Fail closed if an approval no longer refers to the submitted source revision."""
    snapshot = task.confirmation_snapshot or {}
    expected_asset_id = snapshot.get("source_asset_id")
    expected_version_id = snapshot.get("source_version_id")
    if not expected_asset_id or not expected_version_id:
        raise _denied(409, "publication_snapshot_invalid", "发布来源信息不完整，请重新提交")
    if (
        expected_asset_id != str(source.id)
        or snapshot.get("source_scope") != source.scope
        or snapshot.get("source_project_id")
        != (str(source.project_id) if source.project_id else None)
        or source.asset_status != "active"
    ):
        raise _denied(409, "publication_source_changed", "来源资料已变更或不可用，请重新提交")
    if source.current_version_id is None or str(source.current_version_id) != expected_version_id:
        raise _denied(409, "publication_source_version_changed", "来源资料已有新版本，请重新提交")
    source_version = (
        await session.execute(
            select(KnowledgeAssetVersion)
            .where(KnowledgeAssetVersion.id == source.current_version_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if source_version is None or source_version.version_status != "active":
        raise _denied(409, "publication_source_version_unavailable", "来源资料当前版本不可用于发布")
    return source_version


async def _render_locked_publication(
    session: AsyncSession,
    caller: CallerContext,
    source: KnowledgeAsset,
    task: ReviewTask,
) -> naming_rules.RenderedNaming:
    snapshot = task.confirmation_snapshot or {}
    await _validate_locked_publication_source(session, source, task)
    try:
        request = NamingPreviewRequest.model_validate(
            {
                "target_scope": snapshot["target_scope"],
                "target_project_id": snapshot.get("target_project_id"),
                "confidentiality_level": snapshot["confidentiality_level"],
                "naming": snapshot["naming"],
            }
        )
    except (KeyError, ValueError) as exc:
        raise _denied(
            409, "publication_snapshot_invalid", "发布命名信息不完整，请重新提交"
        ) from exc
    rendered = await naming_rules.render_asset_publication(session, caller, source, request)
    if rendered.rule_version != snapshot.get(
        "naming_rule_version"
    ) or rendered.canonical_name != snapshot.get("canonical_name"):
        raise _denied(409, "publication_naming_changed", "目标命名规则已更新，请修改后重新提交")
    return rendered


async def _copy_publication_asset(
    session: AsyncSession,
    *,
    source: KnowledgeAsset,
    target_scope: str,
    target_project_id: uuid.UUID | None,
    actor_user_id: uuid.UUID,
    confidentiality_level: str,
    rendered: naming_rules.RenderedNaming,
) -> KnowledgeAsset:
    existing = (
        await session.execute(
            select(KnowledgeAsset).where(
                KnowledgeAsset.source_asset_id == source.id,
                KnowledgeAsset.scope == target_scope,
                KnowledgeAsset.project_id.is_(None)
                if target_project_id is None
                else KnowledgeAsset.project_id == target_project_id,
                KnowledgeAsset.asset_status == "active",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    source_version = await session.get(KnowledgeAssetVersion, source.current_version_id)
    if source_version is None or source_version.version_status != "active":
        raise _denied(409, "publication_source_version_unavailable", "来源资料当前版本不可用于发布")

    metadata = rendered.metadata
    target = KnowledgeAsset(
        title=str(metadata.get("subject") or source.title),
        scope=target_scope,
        zone="material" if target_scope == KnowledgeScope.project.value else "asset",
        asset_type=str(metadata.get("asset_type") or source.asset_type),
        owner_user_id=source.owner_user_id,
        maintainer_user_id=actor_user_id,
        project_id=target_project_id,
        source_asset_id=source.id,
        visibility="project_only" if target_scope == KnowledgeScope.project.value else "public",
        confidentiality_level=confidentiality_level,
        ai_access_level=source.ai_access_level,
        asset_status="active",
        canonical_name=rendered.canonical_name,
    )
    session.add(target)
    await session.flush()
    target_version = KnowledgeAssetVersion(
        asset_id=target.id,
        version_no=str(metadata.get("version") or source_version.version_no),
        version_status="active",
        file_hash=source_version.file_hash,
        version_hash=source_version.version_hash,
        source_hash=source_version.source_hash,
        change_summary="由受控跨知识库发布生成",
        created_by=actor_user_id,
        index_status="indexing",
        naming_metadata=metadata,
        naming_rule_version=rendered.rule_version,
        directory_key=str(metadata["directory_key"]),
        directory_rule_version=int(metadata["directory_rule_version"]),
        directory_confirmed_by=actor_user_id,
        activated_at=datetime.now(timezone.utc),
    )
    session.add(target_version)
    await session.flush()
    target.current_version_id = target_version.id

    source_tags = (
        await session.execute(
            select(KnowledgeAssetTag).where(KnowledgeAssetTag.asset_id == source.id)
        )
    ).scalars()
    for tag in source_tags:
        session.add(KnowledgeAssetTag(asset_id=target.id, tag_name=tag.tag_name))
    source_chunks = (
        await session.execute(
            select(KnowledgeAssetChunk).where(KnowledgeAssetChunk.version_id == source_version.id)
        )
    ).scalars()
    for chunk in source_chunks:
        session.add(
            KnowledgeAssetChunk(
                asset_id=target.id,
                version_id=target_version.id,
                chunk_index=chunk.chunk_index,
                chunk_type=chunk.chunk_type,
                content_text=chunk.content_text,
                source_page=chunk.source_page,
                source_section=chunk.source_section,
                token_count=chunk.token_count,
                chunk_hash=chunk.chunk_hash,
                chunk_status=chunk.chunk_status,
            )
        )
    source_files = (
        await session.execute(
            select(KnowledgeAssetFileObject).where(
                KnowledgeAssetFileObject.version_id == source_version.id
            )
        )
    ).scalars()
    for file_object in source_files:
        session.add(
            KnowledgeAssetFileObject(
                asset_id=target.id,
                version_id=target_version.id,
                file_variant=file_object.file_variant,
                file_name=(
                    rendered.canonical_name
                    if file_object.file_variant == "original"
                    else file_object.file_name
                ),
                file_mime_type=file_object.file_mime_type,
                file_size=file_object.file_size,
                storage_ref=file_object.storage_ref,
                file_hash=file_object.file_hash,
                confidentiality_level=confidentiality_level,
            )
        )
    source_summaries = (
        await session.execute(
            select(KnowledgeAssetSummary).where(
                KnowledgeAssetSummary.version_id == source_version.id
            )
        )
    ).scalars()
    for summary in source_summaries:
        session.add(
            KnowledgeAssetSummary(
                asset_id=target.id,
                version_id=target_version.id,
                summary_type=summary.summary_type,
                content=summary.content,
            )
        )
    await session.flush()
    return target


# 附件 metadata 黑名单：禁止携带真实 URL / 文件路径 / 内部存储引用 / 凭证。
_FORBIDDEN_ATTACHMENT_KEYS = {
    "url",
    "download_url",
    "file_url",
    "path",
    "storage_ref",
    "source_file_ref",
    "bucket",
    "object_key",
    "token",
}
_FORBIDDEN_VALUE_PREFIXES = (
    "http://",
    "https://",
    "file://",
    "s3://",
    "oss://",
    "internal://",
)


def _validate_attachments(attachments: list[dict] | None) -> None:
    """拒绝携带真实 URL / 路径 / 内部引用 / 凭证的附件 metadata（422）。"""
    if not attachments:
        return
    for item in attachments:
        for key, val in item.items():
            if str(key).lower() in _FORBIDDEN_ATTACHMENT_KEYS:
                raise _denied(
                    422,
                    "attachment_metadata_forbidden",
                    f"附件 metadata 不允许包含字段：{key}",
                )
            if isinstance(val, str):
                low = val.lower()
                if any(low.startswith(p) for p in _FORBIDDEN_VALUE_PREFIXES):
                    raise _denied(
                        422,
                        "attachment_metadata_forbidden",
                        "附件 metadata 不允许包含真实 URL / 路径 / 内部引用",
                    )


def _is_governance(caller: CallerContext) -> bool:
    return governance_policy.is_governance(caller)


def _company_can_decide(
    caller: CallerContext,
    task: ReviewTask,
    states: dict[str, CompanyAssetReviewDecision],
) -> bool:
    if task.status != ReviewTaskStatus.pending_reviewer.value:
        return False
    roles = caller.active_company_roles & governance_policy.GOVERNANCE_COMPANY_ROLES
    return any(
        role not in states or states[role].decision != CompanyAssetDecision.confirmed.value
        for role in roles
    )


def _company_can_withdraw(
    caller: CallerContext,
    task: ReviewTask,
    states: dict[str, CompanyAssetReviewDecision],
) -> bool:
    return task.status == ReviewTaskStatus.pending_reviewer.value and any(
        row.decision == CompanyAssetDecision.confirmed.value and row.actor_user_id == caller.user_id
        for row in states.values()
    )


def _to_list_item(
    task: ReviewTask,
    assets,
    projects,
    *,
    can_decide: bool = False,
    can_withdraw: bool = False,
    decision_states: dict[str, CompanyAssetReviewDecision] | None = None,
) -> ReviewListItem:
    states = decision_states or {}
    return ReviewListItem(
        id=task.id,
        review_type=task.review_type,
        trigger_source=task.trigger_source,
        status=task.status,
        target_asset_id=task.target_asset_id,
        asset_title=assets.get(task.target_asset_id)
        or (
            str(task.confirmation_snapshot.get("title"))
            if task.confirmation_snapshot and task.confirmation_snapshot.get("title")
            else None
        ),
        target_scope=task.target_scope,
        target_project_id=task.target_project_id,
        project_name=projects.get(task.target_project_id) if task.target_project_id else None,
        submitted_by=task.submitted_by,
        reviewer_user_id=task.reviewer_user_id,
        evidence_count=len(task.evidence_links),
        can_decide=can_decide,
        can_withdraw=can_withdraw,
        blocking_reason=(
            "资料资产化需要至少一项验证证据；请登记适用场景和说明后再交审核人。"
            if task.review_type == ReviewType.material_to_asset.value
            and task.status == ReviewTaskStatus.pending_evidence.value
            else (
                "上次处理未完成，可在确认业务条件未变化后重试。"
                if task.status == ReviewTaskStatus.approval_failed.value
                else None
            )
        ),
        general_manager_confirmation_status=(
            states[CompanyRole.boss.value].decision if CompanyRole.boss.value in states else None
        ),
        consulting_director_confirmation_status=(
            states[CompanyRole.consulting_director.value].decision
            if CompanyRole.consulting_director.value in states
            else None
        ),
        review_comment=task.review_comment,
        reviewed_at=task.reviewed_at,
        created_at=task.created_at,
    )


def _can_view(caller: CallerContext, task: ReviewTask, is_pm: bool) -> bool:
    return (
        task.submitted_by == caller.user_id
        or task.reviewer_user_id == caller.user_id
        or (task.review_type == ReviewType.project_to_company.value and _is_governance(caller))
        or is_pm
    )


def _can_decide_project_ingest(caller: CallerContext, task: ReviewTask) -> bool:
    return bool(
        task.target_project_id is not None
        and caller.active_project_roles.get(task.target_project_id)
        == ProjectRole.project_manager.value
    )

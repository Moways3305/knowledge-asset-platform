"""Persistence boundary for a validated ingest confirmation."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingest import IngestTask, UploadSessionItem
from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetSummary,
    KnowledgeAssetTag,
    KnowledgeAssetVersion,
)
from app.schemas.enums import (
    AuditAction,
    AuditLogType,
    ConfidentialityLevel,
    IngestStatus,
)
from app.services import audit as audit_service
from app.services.authorized_summary import build_authorized_summary_variants
from app.services.ingest_confirmation import ValidatedConfirmationContext

_REDACTED_LEVELS = {ConfidentialityLevel.L3.value, ConfidentialityLevel.L4.value}


@dataclass(frozen=True, slots=True)
class PersistedConfirmation:
    task: IngestTask
    asset: KnowledgeAsset
    version: KnowledgeAssetVersion
    use_indexing: bool


def build_summaries(
    level: str,
    *,
    one_liner: str | None,
    detailed: str,
    key_points: list[str],
) -> list[KnowledgeAssetSummary]:
    """Build the persisted summary variants from human-confirmed fields."""
    one = (one_liner or detailed)[:200]
    rows = [
        KnowledgeAssetSummary(summary_type="one_liner", content=one),
        KnowledgeAssetSummary(summary_type="detailed", content=detailed),
    ]
    points = [point.strip() for point in key_points if point and point.strip()]
    if points:
        rows.append(
            KnowledgeAssetSummary(
                summary_type="key_points",
                content="\n".join(points),
            )
        )
    if level in _REDACTED_LEVELS:
        redacted_one_liner, redacted_detailed = build_authorized_summary_variants(
            one_liner=one_liner,
            detailed=detailed,
        )
        if redacted_one_liner:
            rows.append(
                KnowledgeAssetSummary(
                    summary_type="redacted_one_liner",
                    content=redacted_one_liner,
                )
            )
        if redacted_detailed:
            rows.append(
                KnowledgeAssetSummary(
                    summary_type="redacted_summary",
                    content=redacted_detailed,
                )
            )
    return rows


async def persist_confirmation(
    session: AsyncSession,
    context: ValidatedConfirmationContext,
    *,
    use_indexing: bool,
) -> PersistedConfirmation:
    """Persist asset/version, corrections, queue convergence, and safe audit."""
    request = context.request
    task = context.task
    summary_text = (request.summary or "").strip() or (request.one_liner or "").strip()
    confidentiality = request.confidentiality_level.value
    asset = KnowledgeAsset(
        title=request.title,
        scope=context.scope,
        zone=request.target_zone.value,
        asset_type=request.asset_type.value,
        owner_user_id=context.owner_id,
        maintainer_user_id=context.caller.user_id,
        project_id=context.project_id,
        visibility=request.visibility.value,
        confidentiality_level=confidentiality,
        ai_access_level=request.ai_access_level.value,
        asset_status="active",
        lifecycle_phase_key=request.lifecycle_phase_key,
    )
    version = KnowledgeAssetVersion(
        version_no="v1",
        version_status="active",
        created_by=context.caller.user_id,
    )
    asset.versions.append(version)
    for summary in build_summaries(
        confidentiality,
        one_liner=request.one_liner,
        detailed=summary_text,
        key_points=request.key_points,
    ):
        summary.version = version
        asset.summaries.append(summary)
    for tag in request.tags:
        asset.tags.append(KnowledgeAssetTag(tag_name=tag))
    session.add(asset)
    await session.flush()

    asset.current_version_id = version.id
    task.result_asset_id = asset.id
    task.result_version_id = version.id
    task.status = IngestStatus.completed.value
    task.target_scope = context.scope
    task.target_project_id = context.project_id
    task.target_zone = asset.zone
    if task.ai_result is not None:
        task.ai_result.human_corrected = True
        task.ai_result.corrected_title = request.title
        task.ai_result.corrected_summary = request.summary
        task.ai_result.corrected_tags = request.tags

    linked_items = (
        (
            await session.execute(
                select(UploadSessionItem).where(UploadSessionItem.ingest_task_id == task.id)
            )
        )
        .scalars()
        .all()
    )
    for linked_item in linked_items:
        linked_item.status = "completed"
        linked_item.safe_error_code = None
        linked_item.safe_error_message = None

    version.index_status = "indexing" if use_indexing else "skipped"
    await audit_service.record_event(
        session,
        caller=context.caller,
        log_type=AuditLogType.operation,
        action=AuditAction.ingest_confirmed.value,
        trace_id=context.trace_id,
        target_type="knowledge_asset",
        target_id=asset.id,
        after={
            "scope": asset.scope,
            "zone": asset.zone,
            "confidentiality_level": asset.confidentiality_level,
            "ai_access_level": asset.ai_access_level,
            "ingest_task_id": str(task.id),
        },
        project_id=context.project_id,
    )
    await session.commit()
    return PersistedConfirmation(
        task=task,
        asset=asset,
        version=version,
        use_indexing=use_indexing,
    )

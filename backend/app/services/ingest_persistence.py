"""Persistence boundary for a validated ingest confirmation."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingest import IngestTask, IngestTaskDerivative, UploadSessionItem
from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetFileObject,
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
from app.services import domain_events
from app.services.authorized_summary import build_authorized_summary_variants
from app.services.canonical_markdown import FILE_VARIANT, MARKDOWN_MIME, canonical_file_name
from app.services.ingest_confirmation import ValidatedConfirmationContext
from app.worker.enqueue import enqueue_outbox_delivery

_REDACTED_LEVELS = {ConfidentialityLevel.L3.value, ConfidentialityLevel.L4.value}


def derived_confirmation_properties(
    context: ValidatedConfirmationContext,
) -> tuple[str, str]:
    """Return server-owned asset type and visibility for a new confirmation."""
    if context.naming_result is not None:
        asset_type = context.naming_result.metadata.get("asset_type")
        if not isinstance(asset_type, str) or not asset_type:
            raise RuntimeError("validated naming result is missing asset type mapping")
    else:
        # Personal/non-enforced naming has no governed category. Keep it
        # explicitly unclassified rather than guessing a deliverable type.
        asset_type = "unclassified"
    visibility = {
        "personal": "confidential",
        "project": "project_only",
        "company": "public",
    }[context.scope]
    return asset_type, visibility


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


async def attach_controlled_file_objects(
    session: AsyncSession,
    *,
    task: IngestTask,
    asset: KnowledgeAsset,
    version: KnowledgeAssetVersion,
    confidentiality: str,
) -> None:
    """Link the retained original and ready canonical Markdown to one version."""
    derivative = (
        await session.execute(
            select(IngestTaskDerivative).where(
                IngestTaskDerivative.ingest_task_id == task.id,
                IngestTaskDerivative.derivative_type == FILE_VARIANT,
                IngestTaskDerivative.status == "ready",
            )
        )
    ).scalar_one_or_none()
    if (
        derivative is None
        or not derivative.storage_ref
        or not derivative.content_hash
        or derivative.generated_at is None
    ):
        raise RuntimeError("canonical_markdown_not_ready")
    derivative.linked_version_id = version.id
    session.add_all(
        [
            KnowledgeAssetFileObject(
                asset_id=asset.id,
                version_id=version.id,
                file_variant="original",
                file_name=task.source_file_name,
                file_mime_type=task.source_file_mime_type or "application/octet-stream",
                file_size=task.source_file_size,
                storage_ref=task.source_file_ref,
                file_hash=task.source_file_hash,
                confidentiality_level=confidentiality,
            ),
            KnowledgeAssetFileObject(
                asset_id=asset.id,
                version_id=version.id,
                file_variant=FILE_VARIANT,
                file_name=canonical_file_name(task.source_file_name),
                file_mime_type=MARKDOWN_MIME,
                file_size=None,
                storage_ref=derivative.storage_ref,
                file_hash=derivative.content_hash,
                confidentiality_level=confidentiality,
            ),
        ]
    )


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
    asset_type, visibility = derived_confirmation_properties(context)
    asset = KnowledgeAsset(
        title=request.title,
        scope=context.scope,
        zone=request.target_zone.value,
        asset_type=asset_type,
        owner_user_id=context.owner_id,
        maintainer_user_id=context.caller.user_id,
        project_id=context.project_id,
        visibility=visibility,
        confidentiality_level=confidentiality,
        # Legacy non-null compatibility value only; no request/AI suggestion
        # participates in new confirmation logic.
        ai_access_level="A1",
        asset_status="active",
        lifecycle_phase_key=None,
        canonical_name=(
            context.naming_result.canonical_name if context.naming_result is not None else None
        ),
    )
    version = KnowledgeAssetVersion(
        version_no="v1",
        version_status="active",
        created_by=context.caller.user_id,
        file_hash=task.source_file_hash,
        source_hash=task.source_file_hash,
        naming_metadata=(
            context.naming_result.metadata if context.naming_result is not None else None
        ),
        naming_rule_version=(
            context.naming_result.rule_version if context.naming_result is not None else None
        ),
        directory_key=(
            context.naming_result.metadata.get("directory_key")
            if context.naming_result is not None
            else request.naming.directory_key
            if request.naming is not None
            else request.directory_key
        ),
        directory_rule_version=(
            context.naming_result.metadata.get("directory_rule_version")
            if context.naming_result is not None
            else context.directory_rule_version
        ),
        directory_confirmed_by=context.caller.user_id,
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

    await attach_controlled_file_objects(
        session,
        task=task,
        asset=asset,
        version=version,
        confidentiality=confidentiality,
    )

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
            "ingest_task_id": str(task.id),
            "naming_warning_codes": (
                [notice.code for notice in context.naming_result.notices]
                if context.naming_result is not None
                else []
            ),
            "naming_warnings_acknowledged": bool(
                context.naming_result is not None and context.naming_result.notices
            ),
            "directory_key": version.directory_key,
            "directory_rule_version": version.directory_rule_version,
        },
        project_id=context.project_id,
    )
    await domain_events.publish(
        session,
        domain_events.DomainEvent(
            event_type=domain_events.INGEST_CONFIRMED,
            aggregate_type="ingest_task",
            aggregate_id=task.id,
            payload=domain_events.safe_payload(
                task_id=task.id,
                asset_id=asset.id,
                project_id=context.project_id,
                status=task.status,
            ),
            idempotency_key=f"ingest-confirmed:{task.id}:{asset.id}",
        ),
    )
    await session.commit()
    await enqueue_outbox_delivery(session)
    return PersistedConfirmation(
        task=task,
        asset=asset,
        version=version,
        use_indexing=use_indexing,
    )

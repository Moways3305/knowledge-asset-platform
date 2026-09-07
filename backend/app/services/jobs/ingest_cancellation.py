"""Cooperative ingest cancellation and retryable controlled-file cleanup."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.utils import utc_now
from app.models.ingest import IngestTask
from app.models.review import ReviewTask
from app.schemas.enums import AuditAction, AuditLogType, IngestStatus
from app.services import audit as audit_service
from app.services.storage import LocalFileStorage, StorageError

_logger = logging.getLogger(__name__)


def _mark_cancelled(task: IngestTask) -> None:
    task.status = IngestStatus.cancelled.value
    task.processing_stage = "cancelled"
    task.processing_worker_id = None
    task.processing_job_id = None
    task.recovery_not_before = None
    task.error_type = None
    task.error_message = None


async def acknowledge_if_requested(
    session: AsyncSession,
    task: IngestTask,
    *,
    lock: bool = False,
) -> bool:
    """Refresh the durable flag and stop at a worker stage boundary.

    ``lock=True`` is used immediately before final result persistence. The row
    remains locked until this function or the caller commits, so cancellation
    cannot race a transition to ``pending_confirmation``.
    """
    if lock:
        requested = await session.scalar(
            select(IngestTask.cancel_requested).where(IngestTask.id == task.id).with_for_update()
        )
        if requested is None:
            await session.rollback()
            return True
        task.cancel_requested = requested
    else:
        await session.refresh(task, attribute_names=["cancel_requested"])
    if not task.cancel_requested:
        return False
    _mark_cancelled(task)
    await session.commit()
    return True


async def cleanup_cancelled_tasks(
    session: AsyncSession,
    storage: LocalFileStorage,
    *,
    limit: int = 100,
    task_ids: tuple[uuid.UUID, ...] | None = None,
    dry_run: bool = False,
) -> int:
    """Delete bytes only after cancellation is already durable.

    A cleanup or database failure leaves the cancelled task row available for
    the next periodic scan. Repeating the operation is safe because controlled
    storage deletion is idempotent.
    """
    conditions = [
        IngestTask.cancel_requested.is_(True),
        IngestTask.status == IngestStatus.cancelled.value,
        IngestTask.cancellation_cleaned_at.is_(None),
        IngestTask.result_asset_id.is_(None),
    ]
    if task_ids:
        conditions.append(IngestTask.id.in_(task_ids))
    tasks = (
        (
            await session.execute(
                select(IngestTask)
                .where(*conditions)
                .options(
                    selectinload(IngestTask.ai_result),
                    selectinload(IngestTask.canonical_markdown),
                )
                .order_by(IngestTask.updated_at, IngestTask.id)
                .limit(max(1, min(limit, 500)))
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    if dry_run:
        await session.rollback()
        return len(tasks)

    review_linked_ids = set(
        (
            await session.execute(
                select(ReviewTask.source_ingest_task_id).where(
                    ReviewTask.source_ingest_task_id.in_([task.id for task in tasks])
                )
            )
        )
        .scalars()
        .all()
    )
    cleaned = 0
    for task in tasks:
        refs = [task.source_file_ref]
        if task.canonical_markdown and task.canonical_markdown.storage_ref:
            refs.append(task.canonical_markdown.storage_ref)
        try:
            for storage_ref in dict.fromkeys(refs):
                if storage_ref:
                    storage.delete(storage_ref)
        except (OSError, StorageError):
            _logger.warning(
                "cancelled_ingest_file_cleanup_failed",
                extra={"result_category": "controlled_file_cleanup_failed"},
            )
            continue
        if task.id in review_linked_ids:
            # The review FK intentionally preserves the cancelled workflow fact.
            # Bytes are gone, and this marker keeps later cleanup scans idempotent.
            task.cancellation_cleaned_at = utc_now()
        else:
            await session.delete(task)
        await audit_service.record_system_event(
            session,
            log_type=AuditLogType.operation,
            action=AuditAction.ingest_cancellation_cleaned.value,
            trace_id=f"ingest-cancellation-cleanup:{task.id}",
            target_type="ingest_task",
            target_id=task.id,
            after={
                "status": IngestStatus.cancelled.value,
                "result_category": "controlled_files_deleted",
                "task_record_retained": task.id in review_linked_ids,
            },
        )
        cleaned += 1
    await session.commit()
    return cleaned


async def acknowledge_unclaimed_cancellations(
    session: AsyncSession,
    *,
    limit: int = 100,
    task_ids: tuple[uuid.UUID, ...] | None = None,
    dry_run: bool = False,
) -> int:
    """Stop cancellation requests that never reached a worker claim."""
    conditions = [
        IngestTask.cancel_requested.is_(True),
        IngestTask.status.not_in(
            {
                IngestStatus.cancelled.value,
                IngestStatus.completed.value,
            }
        ),
        IngestTask.processing_job_id.is_(None),
        IngestTask.result_asset_id.is_(None),
    ]
    if task_ids:
        conditions.append(IngestTask.id.in_(task_ids))
    tasks = (
        (
            await session.execute(
                select(IngestTask)
                .where(*conditions)
                .order_by(IngestTask.updated_at, IngestTask.id)
                .limit(max(1, min(limit, 500)))
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    if dry_run:
        await session.rollback()
        return len(tasks)
    for task in tasks:
        _mark_cancelled(task)
    if tasks:
        await session.commit()
    return len(tasks)


async def mark_stopped_task_cancelled(session: AsyncSession, task: IngestTask) -> None:
    """Terminalize a cancellation discovered by the stale-worker scanner."""
    _mark_cancelled(task)

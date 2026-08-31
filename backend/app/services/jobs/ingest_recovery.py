"""Business-lease recovery for ingest jobs killed outside Python (OOM/SIGKILL/restart)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.utils import utc_now
from app.models.ingest import IngestTask
from app.schemas.enums import AlertSeverity, AuditAction, AuditLogType, AuditRiskLevel, IngestStatus
from app.services import audit as audit_service
from app.services.storage import LocalFileStorage, StorageError

ACTIVE_STAGES = {
    "processing_claimed",
    "text_extraction",
    "ocr_queued",
    "ocr_in_progress",
    "canonical_markdown_generation",
    "content_generation_queued",
    "content_generation",
}


@dataclass(frozen=True)
class RecoveryCandidate:
    task_id: uuid.UUID
    queue: str
    countdown: int


@dataclass(frozen=True)
class RecoverySummary:
    scanned: int
    scheduled: tuple[RecoveryCandidate, ...]
    source_unavailable: int
    exhausted: int


def _has_source_bytes(storage: LocalFileStorage, task: IngestTask) -> bool:
    try:
        path = storage.resolve_path(task.source_file_ref)
        return path.is_file() and path.stat().st_size > 0
    except (StorageError, OSError):
        return False


def _is_heavy(task: IngestTask) -> bool:
    mime = (task.source_file_mime_type or "").lower()
    name = task.source_file_name.lower()
    return (
        mime == "application/pdf"
        or mime.startswith("image/")
        or name.endswith((".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"))
    )


def _recovery_queue(task: IngestTask) -> str:
    settings = get_settings()
    if task.processing_stage in {
        "canonical_markdown_generation",
        "content_generation_queued",
        "content_generation",
    }:
        return settings.celery_default_queue
    return settings.celery_ocr_queue if _is_heavy(task) else settings.celery_default_queue


async def recover_stale_tasks(
    session: AsyncSession,
    storage: LocalFileStorage,
    *,
    now=None,
    limit: int = 100,
    dry_run: bool = False,
    task_ids: tuple[uuid.UUID, ...] | None = None,
) -> RecoverySummary:
    """Classify stale leases and schedule only bounded, byte-backed recoveries.

    No source reference or path is written to logs/audit. Repeated scans are idempotent because
    candidates leave ACTIVE_STAGES in the same transaction that records the audit event.
    """
    settings = get_settings()
    current = now or utc_now()
    cutoff = current - timedelta(seconds=max(30, settings.ingest_lease_timeout_seconds))
    conditions = [
        IngestTask.status == IngestStatus.processing.value,
        IngestTask.processing_stage.in_(ACTIVE_STAGES),
        func.coalesce(IngestTask.processing_heartbeat_at, IngestTask.updated_at) < cutoff,
    ]
    if task_ids:
        conditions.append(IngestTask.id.in_(task_ids))
    tasks = (
        (
            await session.execute(
                select(IngestTask)
                .where(*conditions)
                .order_by(func.coalesce(IngestTask.processing_heartbeat_at, IngestTask.updated_at))
                .limit(max(1, min(limit, 500)))
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    scheduled: list[RecoveryCandidate] = []
    source_unavailable = 0
    exhausted = 0
    for task in tasks:
        if not _has_source_bytes(storage, task):
            source_unavailable += 1
            if dry_run:
                continue
            task.status = IngestStatus.failed.value
            task.processing_stage = "source_unavailable"
            task.error_type = "source_file_unavailable"
            task.error_message = "原文件不可用，请重新选择原文件。"
            reason = "source_file_unavailable"
        elif task.retry_count >= min(task.max_retries, settings.ingest_recovery_max_attempts):
            exhausted += 1
            if dry_run:
                continue
            task.status = IngestStatus.failed.value
            task.processing_stage = "processing_interrupted"
            task.error_type = "worker_lost_recovery_exhausted"
            task.error_message = "处理多次中断，请重试处理或联系管理员。"
            reason = "worker_lost_recovery_exhausted"
        else:
            delay = min(
                3600,
                max(1, settings.ingest_recovery_base_delay_seconds) * (2**task.retry_count),
            )
            queue = _recovery_queue(task)
            scheduled.append(RecoveryCandidate(task.id, queue, delay))
            if dry_run:
                continue
            task.retry_count += 1
            task.processing_stage = "processing_interrupted"
            interruption_code = (
                "worker_lost" if task.processing_worker_id else "broker_or_container_restart"
            )
            task.error_type = interruption_code
            task.error_message = "处理意外中断，系统已安排有限重试。"
            task.recovery_not_before = current + timedelta(seconds=delay)
            reason = f"{interruption_code}_recovery_scheduled"
        if not dry_run:
            task.processing_heartbeat_at = current
            task.processing_worker_id = None
            task.processing_job_id = None
            await audit_service.record_system_event(
                session,
                log_type=AuditLogType.exception,
                action=AuditAction.ingest_failed.value,
                trace_id=f"ingest-recovery-{task.id}",
                target_type="ingest_task",
                target_id=task.id,
                severity=AlertSeverity.warning,
                risk_level=AuditRiskLevel.high.value,
                extra={
                    "error_code": reason,
                    "retry_count": task.retry_count,
                    "recovery_scheduled": reason.endswith("scheduled"),
                },
            )
    if not dry_run:
        await session.commit()
    return RecoverySummary(len(tasks), tuple(scheduled), source_unavailable, exhausted)

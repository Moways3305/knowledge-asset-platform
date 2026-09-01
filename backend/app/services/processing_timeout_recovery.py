"""Controlled recovery for terminal historical ``processing_timeout`` tasks.

Responses and dry-run audits contain aggregate safety metadata only. Storage references,
filenames, hashes, task identifiers and business text never leave this service.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.utils import utc_now
from app.models.audit import AuditEvent
from app.models.ingest import IngestTask, UploadSessionItem
from app.schemas.enums import AuditAction, AuditLogType, CompanyRole, IngestStatus
from app.schemas.ingest_recovery import (
    ProcessingTimeoutPreflight,
    ProcessingTimeoutRecoveryRequest,
    ProcessingTimeoutRecoveryResponse,
)
from app.schemas.permission import CallerContext
from app.services import audit as audit_service
from app.services.desensitization import DesensitizationEngine
from app.services.llm_client import LLMClient, NullLLMClient
from app.services.storage import LocalFileStorage
from app.worker.enqueue import enqueue_ingest_processing

_DRY_RUN_ACTION = AuditAction.ingest_timeout_recovery_dry_run.value
_REJECTED_ACTION = AuditAction.ingest_timeout_recovery_preflight_rejected.value
_CONFIRMED_ACTION = AuditAction.ingest_timeout_recovery_confirmed.value
_ENQUEUE_ACTION = AuditAction.ingest_timeout_recovery_enqueued.value
_ENQUEUE_FAILED_ACTION = AuditAction.ingest_timeout_recovery_enqueue_failed.value


@dataclass(frozen=True, slots=True)
class _RuntimeFacts:
    redis_ready: bool
    ocr_worker_ready: bool
    queued: int
    oom_kill_count: int


def _require_operator(caller: CallerContext) -> None:
    from fastapi import HTTPException

    if CompanyRole.admin.value in caller.active_company_roles or caller.can_discover_l5:
        return
    raise HTTPException(
        403,
        detail={
            "denied_reason": "ingest_timeout_recovery_forbidden",
            "message": "无权执行超时任务恢复",
        },
    )


def _oom_kill_count() -> int:
    for candidate in (
        Path("/sys/fs/cgroup/memory.events"),
        Path("/sys/fs/cgroup/memory/memory.oom_control"),
    ):
        try:
            for line in candidate.read_text(encoding="utf-8").splitlines():
                key, _, raw = line.partition(" ")
                if key in {"oom_kill", "oom_kill_disable"} and raw.strip().isdigit():
                    return int(raw.strip())
        except OSError:
            continue
    return 0


async def runtime_facts() -> _RuntimeFacts:
    settings = get_settings()
    if settings.celery_task_always_eager:
        return _RuntimeFacts(True, True, 0, _oom_kill_count())
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(
            settings.celery_broker_url or settings.redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        try:
            redis_ready = bool(await client.ping())
            queued = int(await client.llen(settings.celery_default_queue)) + int(
                await client.llen(settings.celery_ocr_queue)
            )
        finally:
            await client.aclose()
    except Exception:  # operational reason is returned as a safe enum, never raw diagnostics
        return _RuntimeFacts(False, False, 0, _oom_kill_count())

    def inspect_workers() -> bool:
        try:
            from app.worker.celery_app import celery_app

            inspector = celery_app.control.inspect(timeout=2)
            pings = inspector.ping() or {}
            queues = inspector.active_queues() or {}
            return bool(
                pings
                and any(
                    any(q.get("name") == settings.celery_ocr_queue for q in worker_queues)
                    for worker_queues in queues.values()
                )
            )
        except Exception:
            return False

    return _RuntimeFacts(
        redis_ready,
        await asyncio.to_thread(inspect_workers),
        queued,
        _oom_kill_count(),
    )


def _preflight(
    facts: _RuntimeFacts, expected_oom_kill_count: int | None
) -> ProcessingTimeoutPreflight:
    settings = get_settings()
    within_budget = facts.queued <= max(1, settings.ingest_timeout_recovery_queue_budget)
    reason = None
    if not facts.redis_ready:
        reason = "redis_unavailable"
    elif not facts.ocr_worker_ready:
        reason = "ocr_worker_unavailable"
    elif not within_budget:
        reason = "queue_budget_exceeded"
    elif expected_oom_kill_count is not None and facts.oom_kill_count != expected_oom_kill_count:
        reason = "oom_kill_count_changed"
    return ProcessingTimeoutPreflight(
        redis_ready=facts.redis_ready,
        ocr_worker_ready=facts.ocr_worker_ready,
        queue_within_budget=within_budget,
        oom_kill_count=facts.oom_kill_count,
        ready=reason is None,
        reason=reason,
    )


async def _candidate_tasks(session: AsyncSession, task_id: uuid.UUID | None) -> list[IngestTask]:
    stmt = (
        select(IngestTask)
        .where(
            IngestTask.source == "path_b_upload",
            IngestTask.status == IngestStatus.failed.value,
            IngestTask.error_type == "processing_timeout",
            IngestTask.result_asset_id.is_(None),
        )
        .order_by(IngestTask.updated_at, IngestTask.id)
    )
    if task_id is not None:
        stmt = stmt.where(IngestTask.id == task_id)
    return list((await session.execute(stmt)).scalars().all())


async def _next_batch_time(session: AsyncSession) -> datetime | None:
    last = (
        await session.execute(
            select(func.max(AuditEvent.created_at)).where(
                AuditEvent.action == _CONFIRMED_ACTION,
                AuditEvent.target_type == "ingest_task_batch",
            )
        )
    ).scalar_one_or_none()
    if last is None:
        return None
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return last + timedelta(
        seconds=max(15, get_settings().ingest_timeout_recovery_interval_seconds)
    )


async def _mark_unavailable(session: AsyncSession, task_ids: list[uuid.UUID]) -> None:
    if not task_ids:
        return
    await session.execute(
        update(IngestTask)
        .where(
            IngestTask.id.in_(task_ids),
            IngestTask.status == IngestStatus.failed.value,
            IngestTask.error_type == "processing_timeout",
        )
        .values(
            processing_stage="source_unavailable",
            error_type="source_file_unavailable",
            error_message="源文件不可用，请重新上传。",
        )
    )
    await session.execute(
        update(UploadSessionItem)
        .where(UploadSessionItem.ingest_task_id.in_(task_ids))
        .values(
            status="failed",
            safe_error_code="source_file_unavailable",
            safe_error_message="源文件不可用，请重新上传",
        )
    )


async def recover(
    session: AsyncSession,
    caller: CallerContext,
    request: ProcessingTimeoutRecoveryRequest,
    *,
    storage: LocalFileStorage,
    llm: LLMClient | NullLLMClient,
    desensitizer: DesensitizationEngine,
    trace_id: str,
    task_id: uuid.UUID | None = None,
) -> ProcessingTimeoutRecoveryResponse:
    _require_operator(caller)
    tasks = await _candidate_tasks(session, task_id)
    available: list[IngestTask] = []
    unavailable: list[uuid.UUID] = []
    for task in tasks:
        if storage.inspect(task.source_file_ref).available:
            available.append(task)
        else:
            unavailable.append(task.id)

    facts = await runtime_facts()
    preflight = _preflight(facts, request.expected_oom_kill_count)
    next_batch = await _next_batch_time(session)
    now = utc_now()
    interval_blocked = bool(not request.dry_run and next_batch is not None and next_batch > now)
    if interval_blocked:
        preflight = preflight.model_copy(
            update={"ready": False, "reason": "batch_interval_not_elapsed"}
        )

    action = _DRY_RUN_ACTION if request.dry_run else _REJECTED_ACTION
    if request.dry_run or not preflight.ready:
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=action,
            trace_id=trace_id,
            target_type="ingest_task_batch",
            extra={
                "dry_run": request.dry_run,
                "scanned": len(tasks),
                "candidates": len(available),
                "source_unavailable": len(unavailable),
                "preflight": "passed" if preflight.ready else preflight.reason,
            },
        )
        await session.commit()
        return ProcessingTimeoutRecoveryResponse(
            dry_run=request.dry_run,
            scanned=len(tasks),
            candidates=len(available),
            source_unavailable=len(unavailable),
            selected=0,
            claimed=0,
            enqueued=0,
            conflicts=0,
            stopped=not preflight.ready,
            stop_reason=preflight.reason,
            preflight=preflight,
            next_batch_not_before=next_batch,
        )

    if request.expected_oom_kill_count is None:
        preflight = preflight.model_copy(
            update={"ready": False, "reason": "oom_baseline_confirmation_required"}
        )
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=_REJECTED_ACTION,
            trace_id=trace_id,
            target_type="ingest_task_batch",
            extra={"reason": preflight.reason, "dry_run": False},
        )
        await session.commit()
        return ProcessingTimeoutRecoveryResponse(
            dry_run=False,
            scanned=len(tasks),
            candidates=len(available),
            source_unavailable=len(unavailable),
            selected=0,
            claimed=0,
            enqueued=0,
            conflicts=0,
            stopped=True,
            stop_reason=preflight.reason,
            preflight=preflight,
            next_batch_not_before=next_batch,
        )

    await _mark_unavailable(session, unavailable)
    selected = available[: min(request.limit, get_settings().ingest_timeout_recovery_batch_size, 3)]
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=_CONFIRMED_ACTION,
        trace_id=trace_id,
        target_type="ingest_task_batch",
        extra={
            "selected": len(selected),
            "source_unavailable": len(unavailable),
            "oom_kill_baseline": facts.oom_kill_count,
        },
    )
    await session.commit()

    claimed = enqueued = conflicts = 0
    for task in selected:
        claim = await session.execute(
            update(IngestTask)
            .where(
                IngestTask.id == task.id,
                IngestTask.source == "path_b_upload",
                IngestTask.status == IngestStatus.failed.value,
                IngestTask.error_type == "processing_timeout",
                IngestTask.result_asset_id.is_(None),
            )
            .values(
                status=IngestStatus.processing.value,
                processing_stage="text_extraction",
                error_type=None,
                error_message=None,
                retry_count=IngestTask.retry_count + 1,
                processing_worker_id=None,
                processing_job_id=None,
                recovery_not_before=None,
            )
        )
        if getattr(claim, "rowcount", 0) != 1:
            await session.rollback()
            conflicts += 1
            continue
        claimed += 1
        await session.commit()
        try:
            await enqueue_ingest_processing(
                session,
                task.id,
                storage=storage,
                llm=llm,
                desensitizer=desensitizer,
                trace_id=trace_id,
            )
        except Exception:
            await session.execute(
                update(IngestTask)
                .where(IngestTask.id == task.id, IngestTask.status == IngestStatus.processing.value)
                .values(
                    status=IngestStatus.failed.value,
                    processing_stage="failed",
                    error_type="processing_timeout",
                    error_message="恢复任务暂时无法排队。",
                )
            )
            await audit_service.record_event(
                session,
                caller=caller,
                log_type=AuditLogType.operation,
                action=_ENQUEUE_FAILED_ACTION,
                trace_id=trace_id,
                target_type="ingest_task",
                target_id=task.id,
                extra={"reason": "queue_unavailable", "result": "not_enqueued"},
                project_id=task.target_project_id,
            )
            await session.commit()
            break
        enqueued += 1
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=_ENQUEUE_ACTION,
            trace_id=trace_id,
            target_type="ingest_task",
            target_id=task.id,
            extra={"queue_route": "existing_ingest_router", "result": "enqueued"},
            project_id=task.target_project_id,
        )
        await session.commit()

    stopped = enqueued < claimed
    return ProcessingTimeoutRecoveryResponse(
        dry_run=False,
        scanned=len(tasks),
        candidates=len(available),
        source_unavailable=len(unavailable),
        selected=len(selected),
        claimed=claimed,
        enqueued=enqueued,
        conflicts=conflicts,
        stopped=stopped,
        stop_reason="queue_unavailable" if stopped else None,
        preflight=preflight,
        next_batch_not_before=utc_now()
        + timedelta(seconds=max(15, get_settings().ingest_timeout_recovery_interval_seconds)),
    )

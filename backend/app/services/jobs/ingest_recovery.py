"""Bounded recovery for upload jobs abandoned by a worker or broker delivery.

This is deliberately database-led: Celery inspect is best-effort and cannot be
trusted across worker restarts.  A worker-owned heartbeat plus Celery late ACKs
gives one durable, observable recovery contract for every supported format.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.utils import utc_now
from app.models.ingest import IngestTask
from app.schemas.enums import IngestStatus
from app.services.desensitization import DesensitizationEngine
from app.services.llm_client import LLMClient, NullLLMClient
from app.services.storage import LocalFileStorage
from app.worker.enqueue import enqueue_ingest_processing

# Must exceed the Celery hard limit (135s) so recovery cannot overlap a worker
# that is still being terminated. Beat adds at most one further 60s interval.
STALE_PROCESSING_SECONDS = 180
RECOVERY_BATCH_SIZE = 100


async def recover_stale_upload_tasks(
    session: AsyncSession,
    *,
    storage: LocalFileStorage,
    llm: LLMClient | NullLLMClient,
    desensitizer: DesensitizationEngine,
) -> dict[str, int]:
    """Requeue stale work once per attempt, then terminalize with a safe code.

    No asset is created here, and ``process_upload_task`` remains idempotent, so
    duplicate delivery cannot create a duplicate knowledge asset or AI draft.
    """
    now = utc_now()
    cutoff = now - timedelta(seconds=STALE_PROCESSING_SECONDS)
    rows = (
        (
            await session.execute(
                select(IngestTask)
                .where(
                    IngestTask.status == IngestStatus.processing.value,
                    IngestTask.result_asset_id.is_(None),
                    or_(
                        (
                            IngestTask.processing_heartbeat_at.is_(None)
                            & (IngestTask.updated_at < cutoff)
                        ),
                        IngestTask.processing_heartbeat_at < cutoff,
                    ),
                )
                .order_by(IngestTask.processing_heartbeat_at, IngestTask.created_at)
                .limit(RECOVERY_BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    requeue_ids: list[uuid.UUID] = []
    terminalized = 0
    for task in rows:
        task.retry_count += 1
        task.processing_heartbeat_at = now
        if task.retry_count >= task.max_retries:
            task.status = IngestStatus.failed.value
            task.processing_stage = "failed"
            task.error_type = "processing_abandoned"
            task.error_message = "后台处理在安全时限内未恢复，已停止；请重试此文件。"
            terminalized += 1
        else:
            task.processing_stage = "upload_saved"
            task.error_type = None
            task.error_message = None
            requeue_ids.append(task.id)
    await session.commit()

    queued = 0
    for task_id in requeue_ids:
        try:
            await enqueue_ingest_processing(
                session,
                task_id,
                storage=storage,
                llm=llm,
                desensitizer=desensitizer,
                trace_id=None,
            )
            queued += 1
        except Exception:
            # The next bounded scan owns another attempt; do not turn a queue outage
            # into an unbounded web request or leak broker details to users.
            continue
    return {"examined": len(rows), "requeued": queued, "failed": terminalized}

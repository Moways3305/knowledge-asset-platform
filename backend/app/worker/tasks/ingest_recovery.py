"""Periodic orphan scanner runs on the ordinary queue, never on the OCR worker."""

from __future__ import annotations

from app.services.storage import get_storage
from app.worker.celery_app import celery_app
from app.worker.runtime import run_task


async def _scan(maker):
    from app.services.jobs.ingest_recovery import recover_stale_tasks

    async with maker() as session:
        return await recover_stale_tasks(session, get_storage())


@celery_app.task(name="ingest.recover_orphans")
def recover_orphaned_ingest_tasks() -> dict[str, int]:
    from app.worker.tasks.ingest import process_ingest_upload

    summary = run_task(_scan, label="ingest.recover_orphans")
    for item in summary.scheduled:
        process_ingest_upload.apply_async(
            args=[str(item.task_id), f"ingest-recovery-{item.task_id}"],
            queue=item.queue,
            countdown=item.countdown,
        )
    return {
        "scanned": summary.scanned,
        "scheduled": len(summary.scheduled),
        "source_unavailable": summary.source_unavailable,
        "exhausted": summary.exhausted,
    }

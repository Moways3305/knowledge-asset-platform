"""生命周期归档扫描 Celery 任务（薄包装，loop-local engine）。"""

from __future__ import annotations

from app.worker.celery_app import celery_app
from app.worker.runtime import run_task


async def _run(maker, trace_id: str | None, resume_only: bool = False) -> None:
    from app.services.jobs import governance_scan, lifecycle_scan
    from app.services.knowledge_review import scan_due_reviews

    async with maker() as session:
        if not resume_only:
            await governance_scan.start_daily_cycles(session)
        result = await lifecycle_scan.scan_archive_candidates(
            session, trace_id=trace_id, resume_only=True
        )
        reviews = await scan_due_reviews(session, resume_only=True)
        pending = await governance_scan.has_pending(session)
    # Each message gives the ordinary queue back its consumer after two short
    # batches. Locked rows and broker failures are picked up by the resume beat.
    if pending and (result["scanned"] or reviews):
        from app.core.config import get_settings

        if not get_settings().celery_task_always_eager:
            import logging

            try:
                archive_scan.apply_async(kwargs={"trace_id": trace_id, "resume_only": True})
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "governance_scan_wakeup_failed", extra={"error_type": type(exc).__name__}
                )


@celery_app.task(name="lifecycle.archive_scan", bind=True)
def archive_scan(self, trace_id: str | None = None, resume_only: bool = False) -> None:
    run_task(
        lambda maker: _run(maker, trace_id, resume_only),
        label="lifecycle.archive_scan",
        trace_id=trace_id,
    )

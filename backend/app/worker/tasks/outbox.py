"""Durable domain-event outbox delivery task."""

from __future__ import annotations

from app.worker.celery_app import celery_app
from app.worker.runtime import run_task


async def _run(maker) -> None:
    from app.core.config import get_settings
    from app.services.outbox import has_ready, process_pending

    async with maker() as session:
        result = await process_pending(session)
        pending = await has_ready(session)
    if (
        pending
        and (result["processed"] or result["failed"])
        and not get_settings().celery_task_always_eager
    ):
        import logging

        try:
            dispatch_pending.delay()
        except Exception as exc:
            # The cursor is durable; the existing 15-second beat resumes it.
            logging.getLogger(__name__).warning(
                "outbox_continuation_failed", extra={"error_type": type(exc).__name__}
            )


@celery_app.task(name="domain_events.dispatch_pending", bind=True)
def dispatch_pending(self) -> None:
    run_task(_run, label="domain_events.dispatch_pending", trace_id=None)

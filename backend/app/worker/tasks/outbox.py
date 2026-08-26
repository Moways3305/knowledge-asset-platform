"""Durable domain-event outbox delivery task."""

from __future__ import annotations

from app.worker.celery_app import celery_app
from app.worker.runtime import run_task


async def _run(maker) -> None:
    from app.services.outbox import process_pending

    async with maker() as session:
        await process_pending(session)


@celery_app.task(name="domain_events.dispatch_pending", bind=True)
def dispatch_pending(self) -> None:
    run_task(_run, label="domain_events.dispatch_pending", trace_id=None)

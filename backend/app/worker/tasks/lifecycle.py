"""生命周期归档扫描 Celery 任务（R5 薄包装；R8_FIX：loop-local engine）。"""

from __future__ import annotations

from app.worker.celery_app import celery_app
from app.worker.runtime import run_task


async def _run(maker, trace_id: str | None) -> None:
    from app.services.jobs import lifecycle_scan

    async with maker() as session:
        await lifecycle_scan.scan_archive_candidates(session, trace_id=trace_id)


@celery_app.task(name="lifecycle.archive_scan", bind=True)
def archive_scan(self, trace_id: str | None = None) -> None:
    run_task(lambda maker: _run(maker, trace_id))

"""Real worker paths for indexing health heartbeat and hourly snapshots."""

from __future__ import annotations

from app.core.config import get_settings
from app.worker.celery_app import celery_app
from app.worker.runtime import run_task


async def _record_worker(maker) -> None:
    from app.services.indexing_health import record_heartbeat

    async with maker() as session:
        await record_heartbeat(session, "worker")


async def _snapshot(maker) -> None:
    from app.services.indexing_health import capture_snapshot, record_heartbeat

    async with maker() as session:
        await record_heartbeat(session, "worker")
        await capture_snapshot(session)


@celery_app.task(
    name="ops.worker_heartbeat", autoretry_for=(Exception,), retry_backoff=True, max_retries=3
)
def worker_heartbeat() -> str:
    if get_settings().celery_task_always_eager:
        return "eager_unknown"
    run_task(_record_worker, label="ops.worker_heartbeat")
    return "recorded"


@celery_app.task(
    name="ops.indexing_health_snapshot",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def indexing_health_snapshot() -> str:
    if get_settings().celery_task_always_eager:
        return "eager_unknown"
    run_task(_snapshot, label="ops.indexing_health_snapshot")
    return "recorded"

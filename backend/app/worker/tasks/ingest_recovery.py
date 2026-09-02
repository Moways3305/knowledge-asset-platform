"""Celery beat entry point for abandoned upload processing recovery."""

from __future__ import annotations

from app.worker.celery_app import celery_app
from app.worker.runtime import run_task


async def _run(maker) -> dict[str, int]:
    from app.services.desensitization import get_desensitizer
    from app.services.generation_models import resolve_generation_llm_client
    from app.services.jobs.ingest_recovery import recover_stale_upload_tasks
    from app.services.storage import get_storage

    async with maker() as session:
        return await recover_stale_upload_tasks(
            session,
            storage=get_storage(),
            llm=await resolve_generation_llm_client(session),
            desensitizer=get_desensitizer(),
        )


@celery_app.task(name="ingest.recover_stale_uploads")
def recover_stale_uploads() -> dict[str, int]:
    return run_task(_run, label="ingest.recover_stale_uploads")

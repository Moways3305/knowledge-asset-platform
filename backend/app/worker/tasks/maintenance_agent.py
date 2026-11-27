"""Beat-driven bounded maintenance tick; each message uses a loop-local engine."""

from app.worker.celery_app import celery_app
from app.worker.runtime import run_task


async def _tick(maker):
    from app.services.maintenance_jobs import tick
    from app.services.maintenance_replacement import recover_archived_replacements

    async with maker() as session:
        await recover_archived_replacements(session)
    await tick(maker)


@celery_app.task(name="maintenance_agent.tick", bind=True)
def maintenance_tick(self):
    run_task(_tick, label="maintenance_agent.tick", trace_id=None)

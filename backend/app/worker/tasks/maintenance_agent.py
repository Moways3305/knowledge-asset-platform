"""Beat-driven bounded maintenance tick; each message uses a loop-local engine."""

from app.worker.celery_app import celery_app
from app.worker.runtime import run_task


@celery_app.task(name="maintenance_agent.tick", bind=True)
def maintenance_tick(self):
    from app.services.maintenance_jobs import tick

    run_task(tick, label="maintenance_agent.tick", trace_id=None)

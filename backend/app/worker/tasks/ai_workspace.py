"""Recover interrupted harness runs through the existing worker infrastructure."""

from app.worker.celery_app import celery_app
from app.worker.runtime import run_task


@celery_app.task(name="ai_workspace.recover")
def recover_workspace():
    from app.services.ai_workspace import recover

    run_task(recover, label="ai_workspace.recover", trace_id=None)

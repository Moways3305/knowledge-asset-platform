"""跨项目复用 / 升格推荐 Celery 任务（薄包装，loop-local engine）。"""

from __future__ import annotations

from app.worker.celery_app import celery_app
from app.worker.runtime import run_task


async def _run(maker, trace_id: str | None, resume_only: bool = False) -> None:
    from app.services.jobs import governance_scan, reuse_upgrade

    async with maker() as session:
        result = await reuse_upgrade.scan_reuse_and_recommend(
            session, trace_id=trace_id, resume_only=resume_only
        )
        pending = await governance_scan.has_pending(session, ("reuse",))
    if pending and result["assets"]:
        from app.core.config import get_settings

        if not get_settings().celery_task_always_eager:
            import logging

            try:
                upgrade_scan.apply_async(kwargs={"trace_id": trace_id, "resume_only": True})
            except Exception as exc:
                # Durable progress + resume beat recover a lost broker wakeup.
                logging.getLogger(__name__).warning(
                    "reuse_scan_wakeup_failed", extra={"error_type": type(exc).__name__}
                )


@celery_app.task(name="reuse.upgrade_scan", bind=True)
def upgrade_scan(self, trace_id: str | None = None, resume_only: bool = False) -> None:
    run_task(
        lambda maker: _run(maker, trace_id, resume_only),
        label="reuse.upgrade_scan",
        trace_id=trace_id,
    )

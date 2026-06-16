"""通知真实下发 Celery 任务（薄包装，loop-local engine）。"""

from __future__ import annotations

from app.worker.celery_app import celery_app
from app.worker.runtime import run_task


async def _run(maker, trace_id: str | None) -> None:
    from app.services.wecom_notification import dispatch_pending, get_wecom_notification_sender

    async with maker() as session:
        await dispatch_pending(session, sender=get_wecom_notification_sender(), trace_id=trace_id)


@celery_app.task(name="notifications.dispatch_pending", bind=True)
def dispatch_pending(self, trace_id: str | None = None) -> None:
    run_task(
        lambda maker: _run(maker, trace_id),
        label="notifications.dispatch_pending",
        trace_id=trace_id,
    )

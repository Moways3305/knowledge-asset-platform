"""通知真实下发 Celery 任务（薄包装，loop-local engine）。"""

from __future__ import annotations

from app.worker.celery_app import celery_app
from app.worker.runtime import run_task


async def _run(maker, trace_id: str | None) -> None:
    from app.core.config import get_settings
    from app.services.notification_delivery import has_ready
    from app.services.notifications import dispatch_pending as dispatch_business_pending
    from app.services.wecom_notification import (
        dispatch_pending as dispatch_ops_pending,
    )
    from app.services.wecom_notification import (
        get_wecom_notification_sender,
    )

    async with maker() as session:
        sender = get_wecom_notification_sender()
        ops = await dispatch_ops_pending(session, sender=sender, trace_id=trace_id)
        business = await dispatch_business_pending(session, sender=sender, trace_id=trace_id)
        # A disabled sender, locked backlog or future retries must not create a
        # busy loop. Each message still gives both channels one bounded batch.
        more = bool(ops["processed"] + business["processed"]) and await has_ready(session)
    if more and not get_settings().celery_task_always_eager:
        import logging

        try:
            dispatch_pending.apply_async(kwargs={"trace_id": trace_id})
        except Exception as exc:
            # Results are already committed. Beat is the durable wakeup fallback.
            logging.getLogger(__name__).warning(
                "notification_dispatch_wakeup_failed", extra={"error_type": type(exc).__name__}
            )


@celery_app.task(name="notifications.dispatch_pending", bind=True)
def dispatch_pending(self, trace_id: str | None = None) -> None:
    run_task(
        lambda maker: _run(maker, trace_id),
        label="notifications.dispatch_pending",
        trace_id=trace_id,
        retain_idle_connections=False,
    )

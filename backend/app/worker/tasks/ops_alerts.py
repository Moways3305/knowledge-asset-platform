"""运维告警信号扫描 Celery 任务（薄包装，loop-local engine）。"""

from __future__ import annotations

from app.worker.celery_app import celery_app
from app.worker.runtime import run_task


async def _run(maker, trace_id: str | None) -> None:
    from app.services.jobs import ops_alerts

    async with maker() as session:
        await ops_alerts.scan_ops_alerts(session, trace_id=trace_id)


@celery_app.task(name="ops.alerts_scan", bind=True)
def alerts_scan(self, trace_id: str | None = None) -> None:
    run_task(lambda maker: _run(maker, trace_id), label="ops.alerts_scan", trace_id=trace_id)

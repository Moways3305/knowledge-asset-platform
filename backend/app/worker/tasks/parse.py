"""WeKnora 解析对账 Celery 任务（R5 薄包装；R8_FIX：loop-local engine）。"""

from __future__ import annotations

from app.worker.celery_app import celery_app
from app.worker.runtime import run_task


async def _run(maker, trace_id: str | None) -> None:
    from app.services.jobs import parse_reconcile
    from app.services.weknora_client import get_weknora_client

    async with maker() as session:
        await parse_reconcile.reconcile_parse_statuses(
            session, get_weknora_client(), trace_id=trace_id
        )


@celery_app.task(name="weknora.parse_reconcile", bind=True)
def reconcile_parse(self, trace_id: str | None = None) -> None:
    run_task(lambda maker: _run(maker, trace_id))

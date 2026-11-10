"""WeKnora 解析对账 Celery 任务（薄包装，loop-local engine）。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from app.worker.celery_app import celery_app
from app.worker.runtime import run_task


async def _run(maker, trace_id: str | None) -> None:
    from app.services.jobs import parse_reconcile
    from app.services.weknora_client import get_weknora_client

    async with maker() as session:
        # run_task creates an engine exclusively owned by this sequential task.
        # Dispose only its idle pool during slow HTTP calls; keep fast batches
        # from opening several fresh PostgreSQL connections per document.
        engine = session.bind
        assert isinstance(engine, AsyncEngine)
        await parse_reconcile.reconcile_parse_statuses(
            session, get_weknora_client(), trace_id=trace_id, release_idle=engine.dispose
        )


# Only this lease-fenced periodic scan opts into redelivery after a lost child.
# A killed process's lease expires naturally; subsequent scans reclaim the row.
@celery_app.task(name="weknora.parse_reconcile", bind=True, reject_on_worker_lost=True)
def reconcile_parse(self, trace_id: str | None = None) -> None:
    run_task(
        lambda maker: _run(maker, trace_id),
        label="weknora.parse_reconcile",
        trace_id=trace_id,
    )

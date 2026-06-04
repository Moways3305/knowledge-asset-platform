"""跨项目复用 / 升格推荐 Celery 任务（R5 薄包装；R8_FIX：loop-local engine）。"""

from __future__ import annotations

from app.worker.celery_app import celery_app
from app.worker.runtime import run_task


async def _run(maker, trace_id: str | None) -> None:
    from app.services.jobs import reuse_upgrade

    async with maker() as session:
        await reuse_upgrade.scan_reuse_and_recommend(session, trace_id=trace_id)


@celery_app.task(name="reuse.upgrade_scan", bind=True)
def upgrade_scan(self, trace_id: str | None = None) -> None:
    run_task(lambda maker: _run(maker, trace_id))

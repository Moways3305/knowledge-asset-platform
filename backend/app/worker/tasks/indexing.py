"""索引批量运维 Celery 任务。"""

from __future__ import annotations

import uuid

from app.worker.celery_app import celery_app
from app.worker.runtime import run_task


async def _run(maker, job_id_str: str, trace_id: str | None) -> None:
    from app.services.jobs import indexing_operations
    from app.services.storage import get_storage
    from app.services.weknora_client import get_weknora_client

    async with maker() as session:
        await indexing_operations.run_operation_job(
            session, uuid.UUID(job_id_str),
            weknora=get_weknora_client(), storage=get_storage(), trace_id=trace_id,
        )


@celery_app.task(name="indexing.run_operation_job", bind=True)
def run_indexing_operation(self, job_id_str: str, trace_id: str | None = None) -> None:
    """异步执行一个索引运维作业（worker 进程内自建 loop-local 会话/客户端）。"""
    run_task(lambda maker: _run(maker, job_id_str, trace_id))


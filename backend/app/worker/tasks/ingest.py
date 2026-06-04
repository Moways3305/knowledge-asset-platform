"""入库处理 Celery 任务（R5 薄包装；R8_FIX：loop-local engine）。"""

from __future__ import annotations

import uuid

from app.worker.celery_app import celery_app
from app.worker.runtime import run_task


async def _run(maker, task_id_str: str, trace_id: str | None) -> None:
    from app.services.desensitization import get_desensitizer
    from app.services.jobs import ingest_processing
    from app.services.llm_client import get_llm_client
    from app.services.storage import get_storage

    async with maker() as session:
        await ingest_processing.process_upload_task(
            session, uuid.UUID(task_id_str),
            storage=get_storage(), llm=get_llm_client(), desensitizer=get_desensitizer(),
            trace_id=trace_id,
        )


@celery_app.task(name="ingest.process_upload", bind=True, max_retries=3)
def process_ingest_upload(self, task_id_str: str, trace_id: str | None = None) -> None:
    """异步处理一个 upload 任务（worker 进程内自建 loop-local 会话/客户端）。"""
    run_task(lambda maker: _run(maker, task_id_str, trace_id))

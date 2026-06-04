"""作业入队工具（R5）。

把"入队"与"执行"解耦，便于：
- eager 模式（默认/本地/测试，无 worker）：在**当前事件循环/会话内联同步执行**，
  避免在已运行的请求事件循环里再 `asyncio.run` 造成嵌套循环错误。
- 非 eager 模式（生产接 worker）：`.delay()` 推到 broker，立即返回，由独立 worker 进程
  自建会话异步执行。

注意：Celery 的真实导入只在非 eager 分支按需发生，app 启动/eager 路径不依赖 broker。
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services.desensitization import DesensitizationEngine
from app.services.llm_client import LLMClient, NullLLMClient
from app.services.storage import LocalFileStorage


async def enqueue_ingest_processing(
    session: AsyncSession,
    task_id: uuid.UUID,
    *,
    storage: LocalFileStorage,
    llm: "LLMClient | NullLLMClient",
    desensitizer: DesensitizationEngine,
    trace_id: str | None,
) -> str:
    """入队入库处理。eager → 内联执行并返回最终 status；非 eager → 排队，返回 processing。"""
    if get_settings().celery_task_always_eager:
        from app.services.jobs import ingest_processing

        return await ingest_processing.process_upload_task(
            session, task_id, storage=storage, llm=llm, desensitizer=desensitizer, trace_id=trace_id
        )
    # 非 eager：推到 broker（真实 worker 自建会话/客户端执行）。
    from app.worker.tasks.ingest import process_ingest_upload

    process_ingest_upload.delay(str(task_id), trace_id)
    return "processing"

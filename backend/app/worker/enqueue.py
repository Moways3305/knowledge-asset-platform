"""作业入队工具。

把"入队"与"执行"解耦，便于：
- eager 模式（默认/本地/测试，无 worker）：在**当前事件循环/会话内联同步执行**，
  避免在已运行的请求事件循环里再 `asyncio.run` 造成嵌套循环错误。
- 非 eager 模式（生产接 worker）：`.delay()` 推到 broker，立即返回，由独立 worker 进程
  自建会话异步执行。

注意：Celery 的真实导入只在非 eager 分支按需发生，app 启动/eager 路径不依赖 broker。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.services.desensitization import DesensitizationEngine
from app.services.llm_client import LLMClient, NullLLMClient
from app.services.storage import LocalFileStorage


async def enqueue_outbox_delivery(session: AsyncSession) -> None:
    """Run only after the publishing transaction committed."""
    if get_settings().celery_task_always_eager:
        from app.services.outbox import process_pending

        # A dispatcher owns its transaction boundary. Reusing the request
        # session would expire/rollback domain objects still needed to build
        # the HTTP response after the publishing transaction committed.
        maker = async_sessionmaker(bind=session.bind, expire_on_commit=False)
        async with maker() as delivery_session:
            await process_pending(delivery_session)
        return
    from app.worker.tasks.outbox import dispatch_pending

    dispatch_pending.delay()


async def enqueue_ingest_processing(
    session: AsyncSession,
    task_id: uuid.UUID,
    *,
    storage: LocalFileStorage,
    llm: LLMClient | NullLLMClient,
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
    from app.models.ingest import IngestTask
    from app.worker.tasks.ingest import process_ingest_upload

    task = (
        await session.execute(select(IngestTask).where(IngestTask.id == task_id))
    ).scalar_one_or_none()
    settings = get_settings()
    # PDF/image rendering is always isolated, even if a particular PDF later proves to have
    # native text. This keeps memory-heavy format inspection away from ordinary jobs.
    mime = (task.source_file_mime_type or "").lower() if task else ""
    name = (task.source_file_name or "").lower() if task else ""
    content_only_stage = bool(
        task
        and task.processing_stage
        in {
            "canonical_markdown_generation",
            "content_generation_queued",
            "content_generation",
            "content_generation_failed",
            "waiting_generation_config",
        }
    )
    heavy = not content_only_stage and (
        mime == "application/pdf"
        or mime.startswith("image/")
        or name.endswith((".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"))
    )
    queue = settings.celery_ocr_queue if heavy else settings.celery_default_queue
    if task is not None:
        task.status = "processing"
        task.processing_stage = (
            "ocr_queued"
            if heavy
            else task.processing_stage
            if content_only_stage
            else "text_extraction"
        )
        await session.commit()
    process_ingest_upload.apply_async(args=[str(task_id), trace_id], queue=queue)
    return "processing"


async def enqueue_indexing_operation(
    session: AsyncSession,
    job_id: uuid.UUID,
    *,
    weknora,
    storage: LocalFileStorage,
    trace_id: str | None,
) -> str:
    """入队索引运维作业。eager → 内联执行并返回最终 status；非 eager → 排队返回 queued。"""
    if get_settings().celery_task_always_eager:
        from app.services.jobs import indexing_operations

        return await indexing_operations.run_operation_job(
            session, job_id, weknora=weknora, storage=storage, trace_id=trace_id
        )
    from app.worker.tasks.indexing import run_indexing_operation

    run_indexing_operation.delay(str(job_id), trace_id)
    return "queued"

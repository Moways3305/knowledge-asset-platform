"""入库处理 Celery 任务（薄包装，loop-local engine）。

瞬时/基础设施异常（逃逸到任务层的网络·超时·DB 连接错误等）经 Celery 原生指数退避自动重试；
service 层已捕获并记录的内容/业务处理失败不在此重试（走其 app-level 失败记录）。
"""

from __future__ import annotations

import logging
import uuid

from app.core.config import get_settings
from app.core.logging import safe_log_exception
from app.worker.celery_app import celery_app
from app.worker.retry import backoff_countdown, is_retryable
from app.worker.runtime import run_task

_logger = logging.getLogger(__name__)


async def _run(
    maker,
    task_id_str: str,
    trace_id: str | None,
    worker_id: str | None,
    job_id: str | None,
) -> str:
    from app.services.ingest_capacity import processing_slot

    async with processing_slot(maker, uuid.UUID(task_id_str)) as admitted:
        if not admitted:
            from sqlalchemy import update

            from app.db.utils import utc_now
            from app.models.ingest import IngestTask

            async with maker() as waiting:
                await waiting.execute(
                    update(IngestTask)
                    .where(
                        IngestTask.id == uuid.UUID(task_id_str),
                        IngestTask.status == "processing",
                        IngestTask.cancel_requested.is_(False),
                    )
                    .values(processing_heartbeat_at=utc_now())
                )
                await waiting.commit()
            return "capacity_wait"
        result = await _process(maker, task_id_str, trace_id, worker_id, job_id)
    # The execution slot is released before dispatching the next file.
    from app.services.upload_window import refill_upload_window

    try:
        await refill_upload_window(maker, uuid.UUID(task_id_str))
    except Exception as exc:
        # Processing has already committed. Beat retries admission independently;
        # never replay a successful extraction because refill failed.
        safe_log_exception(
            _logger,
            "upload_window_refill_deferred",
            exc,
            include_summary=False,
            level=logging.WARNING,
            task_id=task_id_str,
        )
    return result


async def _process(maker, task_id_str, trace_id, worker_id, job_id):
    from app.services.desensitization import get_desensitizer
    from app.services.generation_models import resolve_generation_llm_client
    from app.services.jobs import ingest_processing
    from app.services.storage import get_storage

    async with maker() as session:
        return await ingest_processing.process_upload_task(
            session,
            uuid.UUID(task_id_str),
            storage=get_storage(),
            llm=await resolve_generation_llm_client(session),
            desensitizer=get_desensitizer(),
            trace_id=trace_id,
            worker_id=worker_id,
            job_id=job_id,
        )


@celery_app.task(
    name="ingest.process_upload",
    bind=True,
    max_retries=3,
    acks_late=True,
    reject_on_worker_lost=False,
    soft_time_limit=660,
    time_limit=720,
)
def process_ingest_upload(self, task_id_str: str, trace_id: str | None = None) -> None:
    """异步处理一个 upload 任务（worker 进程内自建 loop-local 会话/客户端）。

    幂等：process_upload_task 内部按 task 当前状态/已建 ai_result 决定是否重做，重试安全。
    """
    try:
        result = run_task(
            lambda maker: _run(
                maker,
                task_id_str,
                trace_id,
                getattr(self.request, "hostname", None),
                getattr(self.request, "id", None),
            ),
            label="ingest.process_upload",
            trace_id=trace_id,
        )
        if result == "capacity_wait":
            # Capacity is not a failed processing attempt. Preserve recovery job identity.
            process_ingest_upload.apply_async(
                args=[task_id_str, trace_id],
                countdown=5,
                queue=(self.request.delivery_info or {}).get("routing_key")
                or get_settings().celery_default_queue,
                task_id=getattr(self.request, "id", None),
            )
        elif result == "content_generation_queued":
            process_ingest_upload.apply_async(
                args=[task_id_str, trace_id],
                queue=get_settings().celery_default_queue,
            )
        elif result.startswith("ocr_retry_scheduled:"):
            countdown = int(result.rsplit(":", 1)[-1])
            process_ingest_upload.apply_async(
                args=[task_id_str, trace_id],
                queue=get_settings().celery_ocr_queue,
                countdown=countdown,
            )
    except Exception as exc:
        if is_retryable(exc) and self.request.retries < self.max_retries:
            countdown = backoff_countdown(self.request.retries)
            # 安全日志：只记 task_id（UUID）/ 重试次数 / 异常类型 / 退避秒数；不记上游异常原文。
            safe_log_exception(
                _logger,
                "ingest_task_retry_scheduled",
                exc,
                include_summary=False,
                level=logging.WARNING,
                task="ingest.process_upload",
                task_id=task_id_str,
                retry=self.request.retries + 1,
                countdown=countdown,
            )
            raise self.retry(exc=exc, countdown=countdown) from exc
        raise  # 不可重试 / 重试耗尽：原样抛出（终态失败按 service 层已记录处理）

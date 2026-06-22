"""入库处理 Celery 任务（薄包装，loop-local engine）。

瞬时/基础设施异常（逃逸到任务层的网络·超时·DB 连接错误等）经 Celery 原生指数退避自动重试；
service 层已捕获并记录的内容/业务处理失败不在此重试（走其 app-level 失败记录）。
"""

from __future__ import annotations

import logging
import uuid

from app.core.logging import safe_log_exception
from app.worker.celery_app import celery_app
from app.worker.retry import backoff_countdown, is_retryable
from app.worker.runtime import run_task

_logger = logging.getLogger(__name__)


async def _run(maker, task_id_str: str, trace_id: str | None) -> None:
    from app.services.desensitization import get_desensitizer
    from app.services.jobs import ingest_processing
    from app.services.llm_client import get_llm_client
    from app.services.storage import get_storage

    async with maker() as session:
        await ingest_processing.process_upload_task(
            session,
            uuid.UUID(task_id_str),
            storage=get_storage(),
            llm=get_llm_client(),
            desensitizer=get_desensitizer(),
            trace_id=trace_id,
        )


@celery_app.task(name="ingest.process_upload", bind=True, max_retries=3)
def process_ingest_upload(self, task_id_str: str, trace_id: str | None = None) -> None:
    """异步处理一个 upload 任务（worker 进程内自建 loop-local 会话/客户端）。

    幂等：process_upload_task 内部按 task 当前状态/已建 ai_result 决定是否重做，重试安全。
    """
    try:
        run_task(
            lambda maker: _run(maker, task_id_str, trace_id),
            label="ingest.process_upload",
            trace_id=trace_id,
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
            raise self.retry(exc=exc, countdown=countdown)
        raise  # 不可重试 / 重试耗尽：原样抛出（终态失败按 service 层已记录处理）

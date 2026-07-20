"""索引批量运维 Celery 任务。

瞬时/基础设施异常（逃逸到任务层的网络·超时·DB 连接错误等）经 Celery 原生指数退避自动重试；
service 层已捕获并记录的逐条/作业级失败不在此重试（走其 app-level 失败记录）。
"""

from __future__ import annotations

import logging
import uuid

from app.core.logging import safe_log_exception
from app.worker.celery_app import celery_app
from app.worker.retry import backoff_countdown, is_retryable
from app.worker.runtime import run_task

_logger = logging.getLogger(__name__)


async def _run(maker, job_id_str: str, trace_id: str | None) -> None:
    from app.services.jobs import indexing_operations
    from app.services.storage import get_storage
    from app.services.weknora_client import get_weknora_client

    async with maker() as session:
        await indexing_operations.run_operation_job(
            session,
            uuid.UUID(job_id_str),
            weknora=get_weknora_client(),
            storage=get_storage(),
            trace_id=trace_id,
        )


@celery_app.task(name="indexing.run_operation_job", bind=True, max_retries=3)
def run_indexing_operation(self, job_id_str: str, trace_id: str | None = None) -> None:
    """异步执行一个索引运维作业（worker 进程内自建 loop-local 会话/客户端）。

    幂等：run_operation_job 按 job 当前状态推进，逐条操作各自检查状态，重试安全。
    """
    try:
        run_task(
            lambda maker: _run(maker, job_id_str, trace_id),
            label="indexing.run_operation_job",
            trace_id=trace_id,
        )
    except Exception as exc:
        if is_retryable(exc) and self.request.retries < self.max_retries:
            countdown = backoff_countdown(self.request.retries)
            safe_log_exception(
                _logger,
                "indexing_task_retry_scheduled",
                exc,
                include_summary=False,
                level=logging.WARNING,
                task="indexing.run_operation_job",
                job_id=job_id_str,
                retry=self.request.retries + 1,
                countdown=countdown,
            )
            raise self.retry(exc=exc, countdown=countdown) from exc
        raise  # 不可重试 / 重试耗尽：原样抛出（终态失败按 service 层已记录处理）

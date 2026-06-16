"""原文访问申请超时自动审批 Celery 任务。

仅在 `access_request_timeout_hours` 规则 enabled、numeric、>0 时生效；只自动审批 L1/L2
pending 申请（机密资产除外）。任务只返回安全统计，不泄露业务原文 / 内部 refs。
"""

from __future__ import annotations

from app.worker.celery_app import celery_app
from app.worker.runtime import run_task


async def _run(maker, trace_id: str | None) -> dict:
    from app.services import original_access

    async with maker() as session:
        return await original_access.auto_approve_timed_out_original_access_requests(
            session,
            trace_id=trace_id or "",
        )


@celery_app.task(name="access.auto_approve_timed_out", bind=True)
def auto_approve_timed_out(self, trace_id: str | None = None) -> dict:
    """返回安全统计：checked / approved / skipped_confidential / skipped_invalid / errors / enabled。"""
    return run_task(
        lambda maker: _run(maker, trace_id),
        label="access.auto_approve_timed_out",
        trace_id=trace_id,
    )

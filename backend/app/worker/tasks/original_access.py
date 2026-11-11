"""原文访问申请超时自动审批 Celery 任务。

仅在 `access_request_timeout_hours` 规则 enabled、numeric、>0 时生效；只自动审批 L1/L2
pending 申请（机密资产除外）。任务只返回安全统计，不泄露业务原文 / 内部 refs。
"""

from __future__ import annotations

from app.worker.celery_app import celery_app
from app.worker.runtime import run_task


async def _run(maker, trace_id: str | None, resume_only: bool = False) -> dict:
    from app.services import original_access
    from app.services.jobs import governance_scan

    async with maker() as session:
        result = await original_access.auto_approve_timed_out_original_access_requests(
            session,
            trace_id=trace_id or "",
            resume_only=resume_only,
        )
        pending = await governance_scan.has_pending(session, ("original_access",))
    if pending and result["checked"]:
        from app.core.config import get_settings

        if not get_settings().celery_task_always_eager:
            import logging

            try:
                auto_approve_timed_out.apply_async(
                    kwargs={"trace_id": trace_id, "resume_only": True}
                )
            except Exception as exc:
                logging.getLogger(__name__).warning(
                    "access_scan_wakeup_failed", extra={"error_type": type(exc).__name__}
                )
    return result


@celery_app.task(name="access.auto_approve_timed_out", bind=True)
def auto_approve_timed_out(self, trace_id: str | None = None, resume_only: bool = False) -> dict:
    """返回安全统计：checked / approved / skipped_confidential / skipped_invalid / errors / enabled。"""
    return run_task(
        lambda maker: _run(maker, trace_id, resume_only),
        label="access.auto_approve_timed_out",
        trace_id=trace_id,
    )

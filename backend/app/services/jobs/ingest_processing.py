"""异步入库处理作业。

把"抽取 + 内容处理 + 写 ai_result + 推进状态"从请求路径迁出。`create_upload`
只持久化字节 + 建 `ingest_tasks`（status=processing）+ 入队；本作业完成重活。

幂等与重试：
- 已处理（pending_confirmation / completed）→ 直接跳过，不重复建 ai_result、不重复
  写终态审计。
- 抽取/内容失败（empty/failed 抽取）→ 写降级 ai_result + status=failed（**内容性终态**，
  非瞬时错误，不增 retry_count）。
- 瞬时异常（读盘/未知错误）→ 递增 retry_count；未达 max_retries 回到 processing 等待
  重试，达到上限置 failed。**绝不**重复创建 ai_result 行、绝不外泄内部引用。

安全：审计/日志只记安全元数据——绝不含 source_file_ref / storage_ref / 抽取全文 /
weknora id / api_key。
"""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.identity import ProjectMember, User
from app.models.ingest import IngestTask, IngestTaskAiResult
from app.schemas.enums import (
    AlertSeverity,
    AuditAction,
    AuditLogType,
    AuditRiskLevel,
    IngestStatus,
)
from app.schemas.permission import CallerContext
from app.services import audit as audit_service
from app.services import content_processing
from app.services.desensitization import DesensitizationEngine
from app.services.extraction import extract_text
from app.services.llm_client import LLMClient, NullLLMClient
from app.services.permission import build_caller_context
from app.services.storage import LocalFileStorage

# 已处理终态（再次入队/重跑直接跳过，保证幂等）。
_PROCESSED_STATUSES = {IngestStatus.pending_confirmation.value, IngestStatus.completed.value}


async def _build_actor(session: AsyncSession, task: IngestTask) -> CallerContext:
    """以任务创建人身份构建审计 actor（作业代其完成内容处理）。"""
    if task.created_by is not None:
        user = (
            await session.execute(
                select(User)
                .where(User.id == task.created_by)
                .options(
                    selectinload(User.company_roles),
                    selectinload(User.project_members).selectinload(ProjectMember.project),
                )
            )
        ).scalar_one_or_none()
        if user is not None:
            return build_caller_context(user)
    # 兜底：无创建人（不应发生）→ 最小 system actor。
    return CallerContext(
        user_id=task.created_by or uuid.UUID(int=0),
        is_active=True,
        active_company_roles=set(),
        active_project_ids=set(),
    )


async def _find_duplicate(session: AsyncSession, content_hash: str, exclude_task_id: uuid.UUID):
    """按内容哈希查最早的既有任务（去重软提示）。返回 (task_id, result_asset_id|None)。"""
    if not content_hash:
        return None
    row = (
        await session.execute(
            select(IngestTask.id, IngestTask.result_asset_id)
            .where(IngestTask.source_file_hash == content_hash)
            .where(IngestTask.id != exclude_task_id)
            .order_by(IngestTask.created_at)
            .limit(1)
        )
    ).first()
    return (row[0], row[1]) if row is not None else None


def _apply_ai_result(task: IngestTask, ai: dict, dup) -> None:
    """把内容处理草稿 upsert 到 task.ai_result（已存在则更新，**不新建第二行**）。"""
    result = task.ai_result
    if result is None:
        result = IngestTaskAiResult(ingest_task_id=task.id)
        task.ai_result = result
    for key, value in ai.items():
        setattr(result, key, value)
    if dup is not None:
        result.duplicate_of_task_id = dup[0]
        result.duplicate_of_asset_id = dup[1]


async def process_upload_task(
    session: AsyncSession,
    task_id: uuid.UUID,
    *,
    storage: LocalFileStorage,
    llm: LLMClient | NullLLMClient,
    desensitizer: DesensitizationEngine,
    trace_id: str | None,
) -> str:
    """处理一个 upload 任务（幂等、可重跑）。返回最终 status。"""
    task = (
        await session.execute(
            select(IngestTask)
            .where(IngestTask.id == task_id)
            .options(selectinload(IngestTask.ai_result))
        )
    ).scalar_one_or_none()
    if task is None:
        return "not_found"

    # 幂等：已成功处理 → 跳过（不重复建 ai_result、不重复写终态审计）。
    if task.status in _PROCESSED_STATUSES:
        return task.status
    # 失败终态 → 跳过。两类都视为已处理，避免重跑重复写 ingest.failed：
    #   (a) 内容性终态（抽取 empty/failed）：已建降级 ai_result（ai_result 不为 None）；
    #   (b) 瞬时失败重试耗尽（retry_count 已达上限）。
    # 仅"瞬时失败且仍有重试额度"会把 status 回退到 processing（不进本分支）→ 可重试。
    if task.status == IngestStatus.failed.value and (
        task.ai_result is not None or task.retry_count >= task.max_retries
    ):
        return task.status

    actor = await _build_actor(session, task)

    # ---- 瞬时区：读盘 + 抽取 + 内容处理。异常 → 递增 retry_count 并退避 ----
    try:
        file_bytes = storage.resolve_path(task.source_file_ref).read_bytes()
        extraction = extract_text(
            file_bytes, file_name=task.source_file_name, mime=task.source_file_mime_type
        )
        content_hash = task.source_file_hash or hashlib.sha256(file_bytes).hexdigest()
        dup = await _find_duplicate(session, content_hash, task.id)
        ai, content_meta = await content_processing.process_content(
            llm,
            desensitizer,
            extraction=extraction,
            file_name=task.source_file_name,
            trace_id=trace_id,
        )
    except Exception as exc:  # noqa: BLE001  # 瞬时处理失败 → 可重试
        task.retry_count += 1
        task.error_type = "processing_error"
        task.error_message = "入库处理失败（详见审计）"  # 安全文案，无内部引用
        exhausted = task.retry_count >= task.max_retries
        task.status = IngestStatus.failed.value if exhausted else IngestStatus.processing.value
        await audit_service.record_event(
            session,
            caller=actor,
            log_type=AuditLogType.exception,
            action=AuditAction.ingest_failed.value,
            trace_id=trace_id,
            target_type="ingest_task",
            target_id=task.id,
            severity=AlertSeverity.warning,
            risk_level=AuditRiskLevel.high.value,
            extra={
                "failure_stage": "processing",
                "error_code": getattr(exc, "code", None) or type(exc).__name__,
                "retry_count": task.retry_count,
                "exhausted": exhausted,
            },
            project_id=task.target_project_id,
        )
        await session.commit()
        return task.status

    # ---- 内容性结果：写 ai_result + 推进状态 ----
    _apply_ai_result(task, ai, dup)
    failed = extraction.status in {"empty", "failed"}
    task.status = IngestStatus.failed.value if failed else IngestStatus.pending_confirmation.value
    if failed:
        task.error_type = extraction.error_type
        task.error_message = extraction.error_message
    else:
        task.error_type = None
        task.error_message = None
    await session.flush()

    if extraction.status == "extracted":
        await audit_service.record_event(
            session,
            caller=actor,
            log_type=AuditLogType.operation,
            action=AuditAction.ingest_ai_extracted.value,
            trace_id=trace_id,
            target_type="ingest_task",
            target_id=task.id,
            extra={
                "content_status": content_meta["status"],
                "degrade_reason": content_meta.get("reason"),
                "llm_provider": content_meta.get("provider"),
                "llm_model": content_meta.get("model"),
                # 入库前置脱敏安全元数据——只记状态与类别计数，**绝不**记脱敏文本/原值。
                "desensitization_status": content_meta.get("desensitization_status"),
                "desensitization_counts": content_meta.get("desensitization_counts"),
            },
            project_id=task.target_project_id,
        )
    if failed:
        await audit_service.record_event(
            session,
            caller=actor,
            log_type=AuditLogType.exception,
            action=AuditAction.ingest_failed.value,
            trace_id=trace_id,
            target_type="ingest_task",
            target_id=task.id,
            severity=AlertSeverity.warning,
            risk_level=AuditRiskLevel.high.value,
            extra={
                "failure_stage": "extraction",
                "extraction_status": extraction.status,
                "error_type": extraction.error_type,
                "source_file_name": task.source_file_name,
                "source_file_mime_type": task.source_file_mime_type,
            },
            project_id=task.target_project_id,
        )
    await session.commit()
    return task.status

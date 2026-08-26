"""Upload-session reconciliation, retry, removal, and safe read workflows."""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ingest import (
    IngestTask,
    UploadSession,
    UploadSessionItem,
)
from app.schemas.enums import IngestStatus
from app.schemas.ingest import UploadSessionListResponse, UploadSessionResponse
from app.schemas.permission import CallerContext
from app.services.desensitization import DesensitizationEngine
from app.services.llm_client import LLMClient, NullLLMClient
from app.services.storage import LocalFileStorage
from app.services.upload_session_commands import RetryClaimConflict, claim_failed_item_retry
from app.services.upload_session_projection import build_response as _response
from app.services.upload_session_repository import _load_owned_session, expire_stale_tasks
from app.services.upload_session_state import TERMINAL_ITEM_STATES as _TERMINAL_ITEM_STATES
from app.services.upload_session_state import task_item_state as _task_item_state
from app.services.upload_session_types import (
    _denied,
)
from app.worker.enqueue import enqueue_ingest_processing


async def _reconcile_and_promote(
    session: AsyncSession,
    session_id: uuid.UUID,
    caller: CallerContext,
    *,
    storage: LocalFileStorage,
    llm: LLMClient | NullLLMClient,
    desensitizer: DesensitizationEngine,
    trace_id: str,
) -> None:
    value = await _load_owned_session(session, caller, session_id, lock=True)
    task_ids = [item.ingest_task_id for item in value.items if item.ingest_task_id]
    await expire_stale_tasks(
        session,
        caller,
        task_ids=task_ids,
        trace_id=trace_id,
    )
    value = await _load_owned_session(session, caller, session_id, lock=True)
    tasks = (
        {
            task.id: task
            for task in (
                await session.execute(select(IngestTask).where(IngestTask.id.in_(task_ids)))
            ).scalars()
        }
        if task_ids
        else {}
    )
    for item in value.items:
        task_id = item.ingest_task_id
        task = tasks.get(task_id) if task_id is not None else None
        if task is not None:
            if item.status != "cancelled":
                item.status = _task_item_state(task)
                if item.status == "failed":
                    item.safe_error_code = task.error_type or "processing_failed"
                    item.safe_error_message = (
                        "文件处理超过安全时限且近期无活动；请重试或移除"
                        if task.error_type == "processing_timeout"
                        else "文件处理失败，请检查文件后重试"
                    )
                else:
                    # A later successful task state is authoritative. Do not retain a stale
                    # parse/queue failure from an earlier reconciliation pass.
                    item.safe_error_code = None
                    item.safe_error_message = None
        elif item.ingest_task_id is not None and item.status != "cancelled":
            # 悬空引用：item 之前关联的 IngestTask 已被删除（例如 delete_pending_task 后
            # ON DELETE SET NULL 清掉了外键）。同步把 item 也置为 cancelled，避免队列里
            # 一直显示"待确认入库"，造成和待确认入库列表/会话统计不同步。
            item.ingest_task_id = None
            item.status = "cancelled"
            item.safe_error_code = None
            item.safe_error_message = None

    batches = sorted({item.batch_index for item in value.items})
    batch_to_promote: int | None = None
    for batch_index in batches:
        items = [item for item in value.items if item.batch_index == batch_index]
        if any(item.status not in _TERMINAL_ITEM_STATES for item in items):
            if all(item.status == "waiting" for item in items if item.ingest_task_id):
                batch_to_promote = batch_index
            break
    promote_items = (
        [
            item
            for item in value.items
            if item.batch_index == batch_to_promote
            and item.status == "waiting"
            and item.ingest_task_id
        ]
        if batch_to_promote is not None
        else []
    )
    for item in promote_items:
        task_id = item.ingest_task_id
        if task_id is None:
            continue
        task = tasks[task_id]
        task.status = IngestStatus.processing.value
        task.processing_stage = "upload_saved"
        item.status = "processing"
    if promote_items:
        await session.commit()

    for item in promote_items:
        task_id = item.ingest_task_id
        if task_id is None:
            continue
        try:
            result = await enqueue_ingest_processing(
                session,
                task_id,
                storage=storage,
                llm=llm,
                desensitizer=desensitizer,
                trace_id=trace_id,
            )
            item.status = (
                "awaiting_confirmation"
                if result == IngestStatus.pending_confirmation.value
                else "failed"
                if result == IngestStatus.failed.value
                else "processing"
            )
            if item.status != "failed":
                item.safe_error_code = None
                item.safe_error_message = None
        except Exception:
            task = tasks[task_id]
            task.status = IngestStatus.failed.value
            task.error_type = "queue_unavailable"
            task.error_message = "处理任务暂时无法排队"
            item.status = "failed"
            item.safe_error_code = "queue_unavailable"
            item.safe_error_message = "处理任务暂时无法排队，请重试"
    value.status = (
        "completed"
        if all(item.status in _TERMINAL_ITEM_STATES for item in value.items)
        else "active"
    )
    await session.commit()

    if promote_items and all(item.status in _TERMINAL_ITEM_STATES for item in promote_items):
        await _reconcile_and_promote(
            session,
            session_id,
            caller,
            storage=storage,
            llm=llm,
            desensitizer=desensitizer,
            trace_id=trace_id,
        )


async def get_session(
    session: AsyncSession,
    caller: CallerContext,
    session_id: uuid.UUID,
    *,
    storage: LocalFileStorage,
    llm: LLMClient | NullLLMClient,
    desensitizer: DesensitizationEngine,
    trace_id: str,
    promote: bool = True,
) -> UploadSessionResponse:
    if not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可查看上传会话")
    value = await _load_owned_session(session, caller, session_id)
    if promote and value.upload_completed:
        await _reconcile_and_promote(
            session,
            session_id,
            caller,
            storage=storage,
            llm=llm,
            desensitizer=desensitizer,
            trace_id=trace_id,
        )
    return await _response(session, caller, await _load_owned_session(session, caller, session_id))


async def list_sessions(
    session: AsyncSession,
    caller: CallerContext,
    *,
    storage: LocalFileStorage,
    llm: LLMClient | NullLLMClient,
    desensitizer: DesensitizationEngine,
    trace_id: str,
) -> UploadSessionListResponse:
    if not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可查看上传会话")
    ids = list(
        (
            await session.execute(
                select(UploadSession.id)
                .where(UploadSession.created_by == caller.user_id)
                .order_by(UploadSession.created_at.desc())
                .limit(10)
            )
        ).scalars()
    )
    items = [
        await get_session(
            session,
            caller,
            session_id,
            storage=storage,
            llm=llm,
            desensitizer=desensitizer,
            trace_id=trace_id,
        )
        for session_id in ids
    ]
    return UploadSessionListResponse(items=items, total=len(items))


async def retry_item(
    session: AsyncSession,
    caller: CallerContext,
    session_id: uuid.UUID,
    item_id: uuid.UUID,
    *,
    storage: LocalFileStorage,
    llm: LLMClient | NullLLMClient,
    desensitizer: DesensitizationEngine,
    trace_id: str,
) -> UploadSessionResponse:
    value = await _load_owned_session(session, caller, session_id)
    item = next((candidate for candidate in value.items if candidate.id == item_id), None)
    if item is None:
        raise _denied(404, "upload_item_not_found", "上传文件不存在")
    if item.status != "failed" or item.ingest_task_id is None:
        raise _denied(409, "upload_item_not_retryable", "该文件当前不可重试")
    task = (
        await session.execute(
            select(IngestTask)
            .where(IngestTask.id == item.ingest_task_id, IngestTask.created_by == caller.user_id)
            .options(
                selectinload(IngestTask.ai_result), selectinload(IngestTask.canonical_markdown)
            )
        )
    ).scalar_one_or_none()
    if task is None or not storage.exists(task.source_file_ref):
        raise _denied(409, "upload_source_unavailable", "源文件不可用，请重新选择文件")
    if task.processing_stage == "waiting_generation_config" and isinstance(llm, NullLLMClient):
        raise _denied(
            409, "generation_model_not_configured", "内容生成模型尚未配置，本次重试未发起"
        )
    resume_stage = (
        "ocr_queued"
        if task.processing_stage == "ocr_failed"
        else "content_generation"
        if task.canonical_markdown and task.canonical_markdown.status == "ready"
        else "text_extraction"
    )
    try:
        await claim_failed_item_retry(
            session,
            session_id=session_id,
            item_id=item.id,
            task_id=task.id,
            owner_id=caller.user_id,
            resume_stage=resume_stage,
        )
    except RetryClaimConflict:
        raise _denied(409, "upload_item_not_retryable", "该文件已被处理或正在重试") from None
    try:
        result = await enqueue_ingest_processing(
            session,
            task.id,
            storage=storage,
            llm=llm,
            desensitizer=desensitizer,
            trace_id=trace_id,
        )
        await session.execute(
            update(UploadSessionItem)
            .where(UploadSessionItem.id == item.id, UploadSessionItem.status == "processing")
            .values(
                status=(
                    "awaiting_confirmation"
                    if result == IngestStatus.pending_confirmation.value
                    else "failed"
                    if result == IngestStatus.failed.value
                    else "processing"
                )
            )
        )
        await session.commit()
    except Exception:
        await session.rollback()
        failure_stage = "ocr_failed" if resume_stage == "ocr_queued" else resume_stage
        await session.execute(
            update(IngestTask)
            .where(IngestTask.id == task.id, IngestTask.status == IngestStatus.processing.value)
            .values(
                status=IngestStatus.failed.value,
                processing_stage=failure_stage,
                error_type="queue_unavailable",
                error_message="处理任务暂时无法排队",
            )
        )
        await session.execute(
            update(UploadSessionItem)
            .where(UploadSessionItem.id == item.id, UploadSessionItem.status == "processing")
            .values(
                status="failed",
                safe_error_code="queue_unavailable",
                safe_error_message="处理任务暂时无法排队，请重试",
            )
        )
        await session.commit()
    session.expire_all()
    return await _response(session, caller, await _load_owned_session(session, caller, session_id))


async def remove_item(
    session: AsyncSession,
    caller: CallerContext,
    session_id: uuid.UUID,
    item_id: uuid.UUID,
    *,
    storage: LocalFileStorage,
) -> UploadSessionResponse:
    value = await _load_owned_session(session, caller, session_id, lock=True)
    item = next((candidate for candidate in value.items if candidate.id == item_id), None)
    if item is None:
        raise _denied(404, "upload_item_not_found", "上传文件不存在")
    if item.status != "failed":
        raise _denied(409, "upload_item_not_failed", "仅可移除终态失败文件")
    if item.ingest_task_id is not None:
        task = (
            await session.execute(
                select(IngestTask).where(
                    IngestTask.id == item.ingest_task_id,
                    IngestTask.created_by == caller.user_id,
                    IngestTask.status == IngestStatus.failed.value,
                    IngestTask.result_asset_id.is_(None),
                )
            )
        ).scalar_one_or_none()
        if task is None:
            raise _denied(
                409,
                "upload_item_cleanup_conflict",
                "该失败项已发生状态变化，请刷新后重试",
            )
        storage.delete(task.source_file_ref)
        await session.delete(task)
        item.ingest_task_id = None
    item.status = "cancelled"
    item.safe_error_code = None
    item.safe_error_message = None
    value.status = (
        "completed"
        if all(candidate.status in _TERMINAL_ITEM_STATES for candidate in value.items)
        else "active"
    )
    await session.commit()
    return await _response(session, caller, await _load_owned_session(session, caller, session_id))


async def remove_failed_items(
    session: AsyncSession,
    caller: CallerContext,
    session_id: uuid.UUID,
    *,
    storage: LocalFileStorage,
) -> UploadSessionResponse:
    """Remove only caller-owned failed tasks and controlled temporary data."""
    value = await _load_owned_session(session, caller, session_id, lock=True)
    for item in [candidate for candidate in value.items if candidate.status == "failed"]:
        if item.ingest_task_id is not None:
            task = (
                await session.execute(
                    select(IngestTask).where(
                        IngestTask.id == item.ingest_task_id,
                        IngestTask.created_by == caller.user_id,
                        IngestTask.status == IngestStatus.failed.value,
                        IngestTask.result_asset_id.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if task is None:
                continue
            storage.delete(task.source_file_ref)
            await session.delete(task)
            item.ingest_task_id = None
        item.status = "cancelled"
        item.safe_error_code = None
        item.safe_error_message = None
    value.status = (
        "completed"
        if all(candidate.status in _TERMINAL_ITEM_STATES for candidate in value.items)
        else "active"
    )
    await session.commit()
    return await _response(session, caller, await _load_owned_session(session, caller, session_id))

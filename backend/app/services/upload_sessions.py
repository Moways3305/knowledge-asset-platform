"""Recoverable, caller-owned local upload sessions with stable 200-item batches."""

from __future__ import annotations

import unicodedata
import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ingest import IngestTask, UploadSession, UploadSessionItem
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetFileObject
from app.schemas.enums import AuditAction, AuditLogType, IngestSource, IngestStatus
from app.schemas.ingest import (
    UploadSessionItemResponse,
    UploadSessionListResponse,
    UploadSessionResponse,
)
from app.schemas.permission import CallerContext
from app.services import audit as audit_service
from app.services.desensitization import DesensitizationEngine
from app.services.llm_client import LLMClient, NullLLMClient
from app.services.permission import discovery_filter
from app.services.storage import LocalFileStorage
from app.worker.enqueue import enqueue_ingest_processing

BATCH_SIZE = 200
_TERMINAL_ITEM_STATES = {"awaiting_confirmation", "completed", "failed", "cancelled"}
_COMPLETED_ITEM_STATES = {"awaiting_confirmation", "completed", "cancelled"}
_PENDING_NAME_WARNING_STATUSES = {
    IngestStatus.pending_confirmation.value,
    IngestStatus.failed.value,
    IngestStatus.rejected.value,
    IngestStatus.waiting_review.value,
}


@dataclass(frozen=True)
class UploadCandidate:
    file_name: str
    file_size: int
    file_type: str | None
    storage_ref: str | None = None
    content_hash: str | None = None
    error_code: str | None = None
    error_message: str | None = None


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"denied_reason": reason, "message": message}
    )


def _display_name(value: str) -> str:
    """Keep a display basename, never a client absolute/relative path."""
    cleaned = "".join(char for char in value if ord(char) >= 32 and ord(char) != 127)
    return (cleaned.replace("\\", "/").rsplit("/", 1)[-1].strip() or "file")[:500]


def _normalized_name(value: str) -> str:
    return unicodedata.normalize("NFKC", _display_name(value)).casefold().strip()


def stable_batch_sizes(total: int) -> list[int]:
    """Pure batching contract used by migrations/tests/UI evidence."""
    if total <= 0:
        return []
    return [min(BATCH_SIZE, total - start) for start in range(0, total, BATCH_SIZE)]


def authorize_create(caller: CallerContext) -> None:
    if not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可发起入库")


async def _visible_names(session: AsyncSession, caller: CallerContext) -> set[str]:
    pending_names = (
        await session.execute(
            select(IngestTask.source_file_name).where(
                IngestTask.created_by == caller.user_id,
                IngestTask.result_asset_id.is_(None),
                IngestTask.status.in_(_PENDING_NAME_WARNING_STATUSES),
            )
        )
    ).scalars()
    materialized_names = (
        await session.execute(
            select(KnowledgeAssetFileObject.file_name)
            .join(KnowledgeAsset, KnowledgeAsset.id == KnowledgeAssetFileObject.asset_id)
            .where(
                KnowledgeAssetFileObject.file_variant == "original",
                discovery_filter(caller),
            )
        )
    ).scalars()
    return {_normalized_name(name) for name in [*pending_names, *materialized_names]}


async def create_session(
    session: AsyncSession,
    caller: CallerContext,
    *,
    requested_session_id: uuid.UUID | None,
    candidates: list[UploadCandidate],
    target_scope: str | None,
    target_project_id: uuid.UUID | None,
    storage: LocalFileStorage,
    llm: LLMClient | NullLLMClient,
    desensitizer: DesensitizationEngine,
    trace_id: str,
) -> UploadSessionResponse:
    authorize_create(caller)
    if not candidates:
        raise _denied(422, "empty_upload_session", "请选择至少一个文件")

    batch_sizes = stable_batch_sizes(len(candidates))
    upload_session = UploadSession(
        id=requested_session_id or uuid.uuid4(),
        created_by=caller.user_id,
        total_files=len(candidates),
        total_batches=len(batch_sizes),
        status="active",
    )
    session.add(upload_session)
    await session.flush()

    existing_names = await _visible_names(session, caller)
    names_seen_in_request: set[str] = set()
    for ordinal, candidate in enumerate(candidates):
        display_name = _display_name(candidate.file_name)
        normalized = _normalized_name(display_name)
        same_name = normalized in existing_names or normalized in names_seen_in_request
        names_seen_in_request.add(normalized)
        item = UploadSessionItem(
            session_id=upload_session.id,
            ordinal=ordinal,
            batch_index=ordinal // BATCH_SIZE,
            file_name=display_name,
            file_size=candidate.file_size,
            file_type=candidate.file_type,
            status="failed" if candidate.error_code else "waiting",
            safe_error_code=candidate.error_code,
            safe_error_message=candidate.error_message,
            same_name_warning=same_name,
        )
        session.add(item)
        if candidate.error_code:
            continue
        if candidate.storage_ref is None or candidate.content_hash is None:
            item.status = "failed"
            item.safe_error_code = "storage_failed"
            item.safe_error_message = "文件暂时无法安全保存，请重试"
            continue
        task = IngestTask(
            source=IngestSource.path_b_upload.value,
            source_file_ref=candidate.storage_ref,
            source_file_name=display_name,
            source_file_mime_type=candidate.file_type,
            source_file_size=candidate.file_size,
            source_file_hash=candidate.content_hash,
            status=IngestStatus.pending.value,
            processing_stage="upload_waiting",
            target_scope=target_scope,
            target_project_id=target_project_id,
            created_by=caller.user_id,
        )
        session.add(task)
        await session.flush()
        item.ingest_task_id = task.id
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.ingest_task_created.value,
            trace_id=trace_id,
            target_type="ingest_task",
            target_id=task.id,
            after={
                "status": task.status,
                "source": task.source,
                "target_scope": task.target_scope,
                "upload_batch_number": item.batch_index + 1,
            },
            project_id=target_project_id,
        )

    await session.commit()
    await _reconcile_and_promote(
        session,
        upload_session.id,
        caller,
        storage=storage,
        llm=llm,
        desensitizer=desensitizer,
        trace_id=trace_id,
    )
    return await get_session(
        session,
        caller,
        upload_session.id,
        storage=storage,
        llm=llm,
        desensitizer=desensitizer,
        trace_id=trace_id,
        promote=False,
    )


async def get_session_if_exists(
    session: AsyncSession,
    caller: CallerContext,
    session_id: uuid.UUID | None,
    *,
    storage: LocalFileStorage,
    llm: LLMClient | NullLLMClient,
    desensitizer: DesensitizationEngine,
    trace_id: str,
) -> UploadSessionResponse | None:
    if session_id is None:
        return None
    owner_id = (
        await session.execute(
            select(UploadSession.created_by).where(UploadSession.id == session_id)
        )
    ).scalar_one_or_none()
    if owner_id is None:
        return None
    if owner_id != caller.user_id:
        raise _denied(409, "upload_session_conflict", "上传会话标识冲突，请重新提交")
    return await get_session(
        session,
        caller,
        session_id,
        storage=storage,
        llm=llm,
        desensitizer=desensitizer,
        trace_id=trace_id,
    )


def _task_item_state(task: IngestTask) -> str:
    if task.status == IngestStatus.pending_confirmation.value:
        return "awaiting_confirmation"
    if task.status in {
        IngestStatus.completed.value,
        IngestStatus.waiting_review.value,
        IngestStatus.rejected.value,
    }:
        return "completed"
    if task.status == IngestStatus.failed.value:
        return "failed"
    if task.status == IngestStatus.pending.value and task.processing_stage == "upload_waiting":
        return "waiting"
    return "processing"


async def _load_owned_session(
    session: AsyncSession, caller: CallerContext, session_id: uuid.UUID, *, lock: bool = False
) -> UploadSession:
    stmt = (
        select(UploadSession)
        .where(UploadSession.id == session_id, UploadSession.created_by == caller.user_id)
        .options(selectinload(UploadSession.items))
    )
    if lock:
        stmt = stmt.with_for_update()
    value = (await session.execute(stmt)).scalar_one_or_none()
    if value is None:
        raise _denied(404, "upload_session_not_found", "上传会话不存在")
    return value


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
        if task is not None and item.status != "cancelled":
            item.status = _task_item_state(task)
            if item.status == "failed":
                item.safe_error_code = task.error_type or "processing_failed"
                item.safe_error_message = "文件处理失败，请检查文件后重试"

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


def _response(value: UploadSession) -> UploadSessionResponse:
    states = [item.status for item in value.items]
    active_batches = [
        item.batch_index for item in value.items if item.status not in _TERMINAL_ITEM_STATES
    ]
    completed = sum(state in _COMPLETED_ITEM_STATES for state in states)
    processing = states.count("processing") + states.count("uploading")
    waiting = states.count("waiting")
    failed = states.count("failed")
    status = "completed" if not active_batches else "active"
    return UploadSessionResponse(
        id=value.id,
        status=status,
        total_files=value.total_files,
        completed_files=completed,
        processing_files=processing,
        waiting_files=waiting,
        failed_files=failed,
        current_batch_number=min(active_batches) + 1 if active_batches else None,
        total_batches=value.total_batches,
        created_at=value.created_at,
        updated_at=value.updated_at,
        items=[
            UploadSessionItemResponse(
                id=item.id,
                ordinal=item.ordinal,
                batch_number=item.batch_index + 1,
                file_name=item.file_name,
                file_size=item.file_size,
                file_type=item.file_type,
                status=item.status,
                error_code=item.safe_error_code,
                error_message=item.safe_error_message,
                same_name_warning=item.same_name_warning,
                retryable=item.status == "failed" and item.ingest_task_id is not None,
            )
            for item in value.items
        ],
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
    if promote:
        await _reconcile_and_promote(
            session,
            session_id,
            caller,
            storage=storage,
            llm=llm,
            desensitizer=desensitizer,
            trace_id=trace_id,
        )
    return _response(await _load_owned_session(session, caller, session_id))


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
    value = await _load_owned_session(session, caller, session_id, lock=True)
    item = next((candidate for candidate in value.items if candidate.id == item_id), None)
    if item is None:
        raise _denied(404, "upload_item_not_found", "上传文件不存在")
    if item.status != "failed" or item.ingest_task_id is None:
        raise _denied(409, "upload_item_not_retryable", "该文件当前不可重试")
    task = (
        await session.execute(
            select(IngestTask).where(
                IngestTask.id == item.ingest_task_id, IngestTask.created_by == caller.user_id
            )
        )
    ).scalar_one_or_none()
    if task is None or not storage.exists(task.source_file_ref):
        raise _denied(409, "upload_source_unavailable", "源文件不可用，请重新选择文件")
    task.status = IngestStatus.pending.value
    task.processing_stage = "upload_waiting"
    task.error_type = None
    task.error_message = None
    item.status = "waiting"
    item.safe_error_code = None
    item.safe_error_message = None
    value.status = "active"
    await session.commit()
    await _reconcile_and_promote(
        session,
        session_id,
        caller,
        storage=storage,
        llm=llm,
        desensitizer=desensitizer,
        trace_id=trace_id,
    )
    return _response(await _load_owned_session(session, caller, session_id))


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
    if item.status in {"processing", "uploading"}:
        raise _denied(409, "upload_item_in_progress", "文件处理中，暂时不能移除")
    if item.ingest_task_id is not None:
        task = (
            await session.execute(
                select(IngestTask).where(
                    IngestTask.id == item.ingest_task_id,
                    IngestTask.created_by == caller.user_id,
                    IngestTask.result_asset_id.is_(None),
                )
            )
        ).scalar_one_or_none()
        if task is not None:
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
    return _response(await _load_owned_session(session, caller, session_id))

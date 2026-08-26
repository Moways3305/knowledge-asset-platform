"""Creation workflow that associates uploaded files with ingest tasks."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingest import (
    UploadSession,
    UploadSessionItem,
)
from app.schemas.enums import AuditAction, AuditLogType
from app.schemas.ingest import UploadSessionResponse
from app.schemas.permission import CallerContext
from app.services import audit as audit_service
from app.services.desensitization import DesensitizationEngine
from app.services.llm_client import LLMClient, NullLLMClient
from app.services.storage import LocalFileStorage
from app.services.upload_ingest_tasks import create_uploaded_ingest_task
from app.services.upload_session_recovery import _reconcile_and_promote, get_session
from app.services.upload_session_repository import _visible_names
from app.services.upload_session_types import (
    BATCH_SIZE,
    UploadCandidate,
    _denied,
    _display_name,
    _normalized_name,
    authorize_create,
    stable_batch_sizes,
)


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
        upload_completed=True,
        next_transport_batch_index=len(batch_sizes),
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
            await session.flush()
            await audit_service.record_event(
                session,
                caller=caller,
                log_type=AuditLogType.operation,
                action=AuditAction.ingest_failed.value,
                trace_id=trace_id,
                target_type="upload_session_item",
                target_id=item.id,
                after={
                    "status": "failed",
                    "error_type": candidate.error_code,
                    "upload_batch_number": item.batch_index + 1,
                },
                project_id=target_project_id,
            )
            continue
        if candidate.storage_ref is None or candidate.content_hash is None:
            item.status = "failed"
            item.safe_error_code = "storage_failed"
            item.safe_error_message = "文件暂时无法安全保存，请重试"
            continue
        task = await create_uploaded_ingest_task(
            session,
            storage_ref=candidate.storage_ref,
            file_name=display_name,
            file_type=candidate.file_type,
            file_size=candidate.file_size,
            content_hash=candidate.content_hash,
            suggested_formed_on=candidate.suggested_formed_on,
            target_scope=target_scope,
            target_project_id=target_project_id,
            created_by=caller.user_id,
        )
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

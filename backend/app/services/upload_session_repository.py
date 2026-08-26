"""Upload-session persistence queries shared by transport and recovery workflows."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ingest import (
    IngestTask,
    UploadSession,
)
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetFileObject
from app.schemas.enums import AuditAction, AuditLogType, IngestSource, IngestStatus
from app.schemas.permission import CallerContext
from app.services import audit as audit_service
from app.services.permission import discovery_filter
from app.services.upload_session_types import (
    _PENDING_NAME_WARNING_STATUSES,
    PROCESSING_ACTIVITY_GRACE,
    PROCESSING_MAX_AGE,
    _denied,
    _is_stale_processing,
    _normalized_name,
)


async def expire_stale_tasks(
    session: AsyncSession,
    caller: CallerContext,
    *,
    task_ids: list[uuid.UUID] | None = None,
    trace_id: str,
    now: datetime | None = None,
    all_owners: bool = False,
) -> int:
    """Fail only caller-owned processing tasks with no recent activity evidence."""
    if all_owners and not ("admin" in caller.active_company_roles or caller.can_discover_l5):
        raise _denied(403, "stale_task_recovery_forbidden", "无权执行全局任务收敛")
    stmt = select(IngestTask).where(
        IngestTask.source == IngestSource.path_b_upload.value,
        IngestTask.status == IngestStatus.processing.value,
        IngestTask.result_asset_id.is_(None),
    )
    if not all_owners:
        stmt = stmt.where(IngestTask.created_by == caller.user_id)
    if task_ids is not None:
        if not task_ids:
            return 0
        stmt = stmt.where(IngestTask.id.in_(task_ids))
    tasks = (await session.execute(stmt.with_for_update())).scalars().all()
    current = now or datetime.now(timezone.utc)
    expired = 0
    for task in tasks:
        if not _is_stale_processing(task, current):
            continue
        task.status = IngestStatus.failed.value
        task.processing_stage = None
        task.error_type = "processing_timeout"
        task.error_message = "文件处理超过安全时限且近期无活动"
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.ingest_failed.value,
            trace_id=trace_id,
            target_type="ingest_task",
            target_id=task.id,
            after={
                "status": task.status,
                "error_type": task.error_type,
                "processing_timeout_minutes": int(PROCESSING_MAX_AGE.total_seconds() / 60),
                "activity_grace_minutes": int(PROCESSING_ACTIVITY_GRACE.total_seconds() / 60),
            },
            project_id=task.target_project_id,
        )
        expired += 1
    if expired:
        await session.commit()
    return expired


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

"""Atomic upload-session item commands with explicit concurrency outcomes."""

from __future__ import annotations

import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingest import IngestTask, UploadSession, UploadSessionItem
from app.schemas.enums import IngestStatus


class RetryClaimConflict(RuntimeError):
    pass


async def claim_failed_item_retry(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
    item_id: uuid.UUID,
    task_id: uuid.UUID,
    owner_id: uuid.UUID,
    resume_stage: str,
    expected_error_type: str | None = None,
) -> None:
    """Atomically claim both item and task; partial claims are rolled back."""
    item_claim = await session.execute(
        update(UploadSessionItem)
        .where(
            UploadSessionItem.id == item_id,
            UploadSessionItem.session_id == session_id,
            UploadSessionItem.ingest_task_id == task_id,
            UploadSessionItem.status == "failed",
        )
        .values(status="processing", safe_error_code=None, safe_error_message=None)
    )
    task_where = [
        IngestTask.id == task_id,
        IngestTask.created_by == owner_id,
        IngestTask.status == IngestStatus.failed.value,
    ]
    if expected_error_type is not None:
        task_where.append(IngestTask.error_type == expected_error_type)
    task_claim = await session.execute(
        update(IngestTask)
        .where(*task_where)
        .values(
            status=IngestStatus.processing.value,
            processing_stage=resume_stage,
            error_type=None,
            error_message=None,
            retry_count=IngestTask.retry_count + 1,
        )
    )
    if getattr(item_claim, "rowcount", 0) != 1 or getattr(task_claim, "rowcount", 0) != 1:
        await session.rollback()
        raise RetryClaimConflict
    await session.execute(
        update(UploadSession)
        .where(UploadSession.id == session_id, UploadSession.created_by == owner_id)
        .values(status="active")
    )
    await session.commit()

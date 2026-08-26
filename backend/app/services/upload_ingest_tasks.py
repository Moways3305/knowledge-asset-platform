"""Creation and association command for ingest tasks backed by uploaded bytes."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingest import IngestTask
from app.schemas.enums import IngestSource, IngestStatus


async def create_uploaded_ingest_task(
    session: AsyncSession,
    *,
    storage_ref: str,
    file_name: str,
    file_type: str | None,
    file_size: int,
    content_hash: str,
    suggested_formed_on: str | None,
    target_scope: str | None,
    target_project_id: uuid.UUID | None,
    created_by: uuid.UUID,
) -> IngestTask:
    task = IngestTask(
        source=IngestSource.path_b_upload.value,
        source_file_ref=storage_ref,
        source_file_name=file_name,
        source_file_mime_type=file_type,
        source_file_size=file_size,
        source_file_hash=content_hash,
        suggested_formed_on=suggested_formed_on,
        status=IngestStatus.pending.value,
        processing_stage="upload_waiting",
        target_scope=target_scope,
        target_project_id=target_project_id,
        created_by=created_by,
    )
    session.add(task)
    await session.flush()
    return task

"""Safe user projection for upload sessions; never returns storage references."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingest import IngestTask, UploadSession
from app.schemas.ingest import UploadSessionItemResponse, UploadSessionResponse
from app.schemas.permission import CallerContext
from app.services.upload_duplicates import read_duplicate
from app.services.upload_session_state import COMPLETED_ITEM_STATES, TERMINAL_ITEM_STATES

_VISIBLE_PROCESSING_STAGES = {
    "upload_saved",
    "text_extraction",
    "ocr_queued",
    "ocr_in_progress",
    "ocr_failed",
    "canonical_markdown_generation",
    "content_generation",
    "waiting_generation_config",
    "content_generation_failed",
    "content_result_persistence_failed",
    "processing_state_persistence_failed",
}


def visible_processing_stage(stage: str | None) -> str | None:
    return stage if stage is not None and stage in _VISIBLE_PROCESSING_STAGES else None


async def build_response(
    session: AsyncSession, caller: CallerContext, value: UploadSession
) -> UploadSessionResponse:
    visible_items = [item for item in value.items if item.status != "cancelled"]
    task_ids = [item.ingest_task_id for item in visible_items if item.ingest_task_id]
    task_facts: dict[uuid.UUID, tuple[str | None, int, str | None, datetime | None]] = {
        task_id: (processing_stage, retry_count, error_type, updated_at)
        for task_id, processing_stage, retry_count, error_type, updated_at in (
            await session.execute(
                select(
                    IngestTask.id,
                    IngestTask.processing_stage,
                    IngestTask.retry_count,
                    IngestTask.error_type,
                    IngestTask.updated_at,
                ).where(IngestTask.id.in_(task_ids))
            )
        ).all()
    }
    tasks = {
        task.id: task
        for task in (
            (await session.execute(select(IngestTask).where(IngestTask.id.in_(task_ids))))
            .scalars()
            .all()
        )
    }
    duplicates = {
        task_id: await read_duplicate(
            session,
            caller,
            task,
            scope=value.target_scope or "",
            project_id=value.target_project_id,
        )
        for task_id, task in tasks.items()
    }
    states = [item.status for item in visible_items]
    active_batches = [
        item.batch_index for item in visible_items if item.status not in TERMINAL_ITEM_STATES
    ]
    return UploadSessionResponse(
        id=value.id,
        status="completed" if value.upload_completed and not active_batches else "active",
        total_files=value.total_files,
        completed_files=sum(state in COMPLETED_ITEM_STATES for state in states),
        processing_files=states.count("processing") + states.count("uploading"),
        waiting_files=states.count("waiting") + states.count("waiting_upload"),
        failed_files=states.count("failed"),
        current_batch_number=min(active_batches) + 1 if active_batches else None,
        total_batches=value.total_batches,
        uploaded_files=sum(item.ingest_task_id is not None for item in visible_items),
        uploaded_batches=value.next_transport_batch_index,
        upload_completed=value.upload_completed,
        created_at=value.created_at,
        updated_at=value.updated_at,
        items=[
            UploadSessionItemResponse(
                id=item.id,
                ordinal=item.ordinal,
                batch_number=item.batch_index + 1,
                transport_batch_number=(
                    item.transport_batch_index + 1
                    if item.transport_batch_index is not None
                    else None
                ),
                file_name=item.file_name,
                file_size=item.file_size,
                file_type=item.file_type,
                status=item.status,
                error_code=item.safe_error_code,
                error_message=item.safe_error_message,
                same_name_warning=item.same_name_warning,
                retryable=(
                    item.status == "failed"
                    and item.ingest_task_id is not None
                    and task_facts.get(item.ingest_task_id, (None, 0, None, None))[2]
                    not in {"configuration_error", "authentication_error", "model_unavailable"}
                ),
                retry_count=(
                    task_facts.get(item.ingest_task_id, (None, 0, None, None))[1]
                    if item.ingest_task_id is not None
                    else 0
                ),
                last_attempt_at=(
                    task_facts.get(item.ingest_task_id, (None, 0, None, None))[3]
                    if item.ingest_task_id is not None
                    else None
                ),
                processing_stage=visible_processing_stage(
                    task_facts.get(item.ingest_task_id, (None, 0, None, None))[0]
                    if item.ingest_task_id is not None
                    else None
                ),
                bytes_available=item.ingest_task_id is not None,
                duplicate=(
                    duplicates.get(item.ingest_task_id) if item.ingest_task_id is not None else None
                ),
            )
            for item in visible_items
        ],
    )

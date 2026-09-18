"""Safe user projection for upload sessions; never returns storage references."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.models.ingest import IngestTask, UploadSession
from app.schemas.ingest import UploadSessionItemResponse, UploadSessionResponse
from app.schemas.permission import CallerContext
from app.services.storage import LocalFileStorage
from app.services.upload_duplicates import read_duplicates_batch
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
    session: AsyncSession,
    caller: CallerContext,
    value: UploadSession,
    *,
    storage: LocalFileStorage,
) -> UploadSessionResponse:
    visible_items = [item for item in value.items if item.status != "cancelled"]
    task_ids = [item.ingest_task_id for item in visible_items if item.ingest_task_id]
    tasks = {
        task.id: task
        for task in (
            (await session.execute(select(IngestTask).where(IngestTask.id.in_(task_ids))))
            .scalars()
            .all()
        )
    }
    task_facts = {
        task.id: (task.processing_stage, task.retry_count, task.error_type, task.updated_at)
        for task in tasks.values()
    }
    source_refs = {task_id: task.source_file_ref for task_id, task in tasks.items()}
    source_available = await run_in_threadpool(
        lambda: {task_id: storage.inspect(ref).available for task_id, ref in source_refs.items()}
    )
    duplicates = await read_duplicates_batch(
        session,
        caller,
        list(tasks.values()),
        destination=(value.target_scope or "", value.target_project_id),
    )
    states = [item.status for item in visible_items]
    active_batches = [
        item.batch_index for item in visible_items if item.status not in TERMINAL_ITEM_STATES
    ]
    return UploadSessionResponse(
        id=value.id,
        status=(
            "cancelled"
            if value.status == "cancelled"
            else "completed"
            if value.upload_completed and not active_batches
            else "active"
        ),
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
                ingest_task_id=item.ingest_task_id,
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
                error_code=(
                    "source_file_unavailable"
                    if item.ingest_task_id is not None
                    and task_facts.get(item.ingest_task_id, (None, 0, None, None))[2]
                    == "processing_timeout"
                    and not source_available.get(item.ingest_task_id, False)
                    else item.safe_error_code
                ),
                error_message=(
                    "源文件不可用，请重新上传"
                    if item.ingest_task_id is not None
                    and task_facts.get(item.ingest_task_id, (None, 0, None, None))[2]
                    == "processing_timeout"
                    and not source_available.get(item.ingest_task_id, False)
                    else "处理超时，文件仍可重试"
                    if item.ingest_task_id is not None
                    and task_facts.get(item.ingest_task_id, (None, 0, None, None))[2]
                    == "processing_timeout"
                    else item.safe_error_message
                ),
                same_name_warning=item.same_name_warning,
                retryable=(
                    item.status == "failed"
                    and item.ingest_task_id is not None
                    and source_available.get(item.ingest_task_id, False)
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
                bytes_available=(
                    item.ingest_task_id is not None
                    and source_available.get(item.ingest_task_id, False)
                ),
                duplicate=(
                    duplicates.get(item.ingest_task_id) if item.ingest_task_id is not None else None
                ),
            )
            for item in visible_items
        ],
    )

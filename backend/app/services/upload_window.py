"""Worker/beat-driven refill, independent of an open browser tab."""

import logging

from sqlalchemy import select

from app.core.logging import safe_log_exception
from app.models.ingest import IngestTask, UploadSession, UploadSessionItem

_logger = logging.getLogger(__name__)


async def refill_upload_window(maker, task_id=None):
    from app.services.desensitization import get_desensitizer
    from app.services.generation_models import resolve_generation_llm_client
    from app.services.jobs.ingest_processing import _build_actor
    from app.services.storage import get_storage
    from app.services.upload_session_recovery import _reconcile_and_promote

    async with maker() as session:
        query = (
            select(UploadSessionItem.session_id, UploadSession.created_at)
            .join(UploadSession, UploadSession.id == UploadSessionItem.session_id)
            .where(
                UploadSession.status != "cancelled",
                UploadSession.upload_completed.is_(True),
                UploadSessionItem.ingest_task_id.is_not(None),
            )
            .distinct()
            .order_by(UploadSession.created_at, UploadSessionItem.session_id)
        )
        if task_id is not None:
            query = query.where(UploadSessionItem.ingest_task_id == task_id)
        else:
            query = query.where(UploadSessionItem.status == "waiting")
        candidates = (await session.execute(query)).all()
    completed = 0
    for session_id, _ in candidates:
        # An invalid/deleted session must not block admission for other users.
        async with maker() as session:
            try:
                task = await session.scalar(
                    select(IngestTask)
                    .join(UploadSessionItem, UploadSessionItem.ingest_task_id == IngestTask.id)
                    .where(UploadSessionItem.session_id == session_id)
                    .order_by(UploadSessionItem.ordinal)
                    .limit(1)
                )
                if task is None:
                    continue
                caller = await _build_actor(session, task)
                await _reconcile_and_promote(
                    session,
                    session_id,
                    caller,
                    storage=get_storage(),
                    llm=await resolve_generation_llm_client(session),
                    desensitizer=get_desensitizer(),
                    trace_id=f"upload-window-{session_id}",
                )
                completed += 1
            except Exception as exc:
                await session.rollback()
                safe_log_exception(
                    _logger,
                    "upload_window_session_deferred",
                    exc,
                    include_summary=False,
                    session_id=str(session_id),
                )
    return completed

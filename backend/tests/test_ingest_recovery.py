from __future__ import annotations

from datetime import timedelta

from app.db.utils import utc_now
from app.models.ingest import IngestTask
from app.schemas.enums import IngestSource, IngestStatus
from app.services.desensitization import get_desensitizer
from app.services.jobs import ingest_recovery
from app.services.llm_client import NullLLMClient
from app.services.storage import get_storage


async def test_stale_worker_job_is_requeued_once_with_a_fresh_heartbeat(db_session, monkeypatch):
    task = IngestTask(
        source=IngestSource.path_b_upload.value,
        source_file_ref="controlled-ref",
        source_file_name="interrupted.txt",
        status=IngestStatus.processing.value,
        max_retries=3,
        processing_heartbeat_at=utc_now() - timedelta(minutes=5),
    )
    db_session.add(task)
    await db_session.commit()
    queued: list[str] = []

    async def fake_enqueue(_session, task_id, **_kwargs):
        queued.append(str(task_id))
        return "processing"

    monkeypatch.setattr(ingest_recovery, "enqueue_ingest_processing", fake_enqueue)
    outcome = await ingest_recovery.recover_stale_upload_tasks(
        db_session,
        storage=get_storage(),
        llm=NullLLMClient(),
        desensitizer=get_desensitizer(),
    )
    await db_session.refresh(task)
    assert outcome == {"examined": 1, "requeued": 1, "failed": 0}
    assert queued == [str(task.id)]
    assert task.status == IngestStatus.processing.value
    assert task.retry_count == 1
    assert task.processing_stage == "upload_saved"
    assert task.processing_heartbeat_at is not None


async def test_stale_worker_job_terminalizes_at_retry_limit(db_session):
    task = IngestTask(
        source=IngestSource.path_b_upload.value,
        source_file_ref="controlled-ref",
        source_file_name="abandoned.txt",
        status=IngestStatus.processing.value,
        retry_count=2,
        max_retries=3,
        processing_heartbeat_at=utc_now() - timedelta(minutes=5),
    )
    db_session.add(task)
    await db_session.commit()
    outcome = await ingest_recovery.recover_stale_upload_tasks(
        db_session,
        storage=get_storage(),
        llm=NullLLMClient(),
        desensitizer=get_desensitizer(),
    )
    await db_session.refresh(task)
    assert outcome == {"examined": 1, "requeued": 0, "failed": 1}
    assert task.status == IngestStatus.failed.value
    assert task.error_type == "processing_abandoned"

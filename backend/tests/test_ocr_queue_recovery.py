from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.db.utils import utc_now
from app.models.audit import AuditEvent
from app.models.ingest import IngestTask
from app.seed.dev_seed import USER_CONSULTANT
from app.services import ocr
from app.services.desensitization import NullDesensitizer
from app.services.extraction import ExtractionPage, ExtractionResult
from app.services.jobs import ingest_processing
from app.services.jobs.ingest_recovery import recover_stale_tasks

pytestmark = pytest.mark.asyncio


def _task(ref: str, *, retry_count: int = 0) -> IngestTask:
    stale = utc_now() - timedelta(hours=2)
    return IngestTask(
        source="path_b_upload",
        source_file_ref=ref,
        source_file_name="incident.pdf",
        source_file_mime_type="application/pdf",
        source_file_size=10,
        status="processing",
        processing_stage="ocr_in_progress",
        processing_started_at=stale,
        processing_heartbeat_at=stale,
        processing_worker_id="ocr@test-host",
        retry_count=retry_count,
    )


async def test_stale_valid_source_gets_bounded_ocr_recovery(client, db_session):
    ref = client._kap_storage.save(b"valid-pdf-bytes", original_name="incident.pdf")
    task = _task(ref)
    db_session.add(task)
    await db_session.commit()

    summary = await recover_stale_tasks(db_session, client._kap_storage)

    await db_session.refresh(task)
    assert len(summary.scheduled) == 1
    assert summary.scheduled[0].queue == get_settings().celery_ocr_queue
    assert task.status == "processing"
    assert task.processing_stage == "processing_interrupted"
    assert task.retry_count == 1
    assert task.processing_job_id is None
    assert task.recovery_not_before is not None
    audits = (await db_session.execute(select(AuditEvent))).scalars().all()
    assert any(
        event.extra.get("error_code") == "worker_lost_recovery_scheduled" for event in audits
    )


@pytest.mark.parametrize("empty", [False, True])
async def test_stale_missing_or_zero_byte_source_requires_reupload(client, db_session, empty):
    ref = (
        client._kap_storage.save(b"", original_name="empty.pdf")
        if empty
        else "internal://missing/incident.pdf"
    )
    task = _task(ref)
    db_session.add(task)
    await db_session.commit()

    summary = await recover_stale_tasks(db_session, client._kap_storage)

    await db_session.refresh(task)
    assert summary.source_unavailable == 1
    assert summary.scheduled == ()
    assert task.status == "failed"
    assert task.processing_stage == "source_unavailable"
    assert task.error_type == "source_file_unavailable"


async def test_dry_run_does_not_mutate_or_audit(client, db_session):
    ref = client._kap_storage.save(b"valid", original_name="incident.pdf")
    task = _task(ref)
    db_session.add(task)
    await db_session.commit()

    summary = await recover_stale_tasks(db_session, client._kap_storage, dry_run=True)

    await db_session.refresh(task)
    assert len(summary.scheduled) == 1
    assert task.processing_stage == "ocr_in_progress"
    assert not (await db_session.execute(select(AuditEvent))).scalars().all()


async def test_recovery_budget_exhaustion_is_terminal_but_manually_retryable(client, db_session):
    ref = client._kap_storage.save(b"valid", original_name="incident.pdf")
    task = _task(ref, retry_count=get_settings().ingest_recovery_max_attempts)
    db_session.add(task)
    await db_session.commit()

    summary = await recover_stale_tasks(db_session, client._kap_storage)

    await db_session.refresh(task)
    assert summary.exhausted == 1
    assert task.status == "failed"
    assert task.processing_stage == "processing_interrupted"
    assert task.error_type == "worker_lost_recovery_exhausted"


async def test_stale_unclaimed_queue_item_identifies_broker_or_restart(client, db_session):
    ref = client._kap_storage.save(b"valid", original_name="incident.pdf")
    task = _task(ref)
    task.processing_worker_id = None
    task.processing_job_id = None
    task.processing_stage = "ocr_queued"
    db_session.add(task)
    await db_session.commit()

    await recover_stale_tasks(db_session, client._kap_storage)

    await db_session.refresh(task)
    assert task.error_type == "broker_or_container_restart"


async def test_due_recovery_is_redispatched_without_spending_retry_budget(client, db_session):
    ref = client._kap_storage.save(b"valid", original_name="incident.pdf")
    task = _task(ref, retry_count=1)
    task.processing_stage = "processing_interrupted"
    task.processing_worker_id = None
    task.processing_job_id = None
    previous_not_before = utc_now() - timedelta(seconds=1)
    task.recovery_not_before = previous_not_before
    db_session.add(task)
    await db_session.commit()

    summary = await recover_stale_tasks(db_session, client._kap_storage)

    await db_session.refresh(task)
    assert summary.redispatched == 1
    assert len(summary.scheduled) == 1
    assert summary.scheduled[0].countdown == 0
    assert summary.scheduled[0].queue == get_settings().celery_ocr_queue
    assert task.retry_count == 1
    assert task.recovery_not_before.replace(tzinfo=previous_not_before.tzinfo) > previous_not_before
    audits = (await db_session.execute(select(AuditEvent))).scalars().all()
    assert any(
        event.extra.get("error_code") == "lost_recovery_message_redispatched" for event in audits
    )


async def test_redispatch_lease_prevents_requeue_storm(client, db_session):
    ref = client._kap_storage.save(b"valid", original_name="incident.pdf")
    task = _task(ref, retry_count=1)
    task.processing_stage = "processing_interrupted"
    task.processing_worker_id = None
    task.processing_job_id = None
    task.recovery_not_before = utc_now() - timedelta(seconds=1)
    db_session.add(task)
    await db_session.commit()

    first = await recover_stale_tasks(db_session, client._kap_storage)
    second = await recover_stale_tasks(db_session, client._kap_storage)

    assert first.redispatched == 1
    assert second.scheduled == ()
    assert second.redispatched == 0
    await db_session.refresh(task)
    assert task.retry_count == 1


async def test_completed_ocr_page_is_skipped_on_resume(monkeypatch):
    extraction = ExtractionResult(
        text="",
        status="ocr_required",
        error_type=None,
        error_message=None,
        char_count=0,
        pages=(
            ExtractionPage(1, "", "ocr_required"),
            ExtractionPage(2, "", "ocr_required"),
        ),
        source_kind="image",
    )
    calls = []

    def fake_page(_content, _extraction, page):
        calls.append(page.page_number)
        return ocr.OCRPageResult(page.page_number, "second", "succeeded", 90.0, 100)

    monkeypatch.setattr(ocr, "recognize_page", fake_page)
    saved = {1: ocr.OCRPageResult(1, "first", "succeeded", 91.0)}

    result = ocr.recognize(b"image", extraction, completed_pages=saved)

    assert calls == [2]
    assert [page.text for page in result.pages] == ["first", "second"]


async def test_ocr_render_timeout_has_distinct_safe_code(monkeypatch):
    extraction = ExtractionResult(
        text="",
        status="ocr_required",
        error_type=None,
        error_message=None,
        char_count=0,
        pages=(ExtractionPage(1, "", "ocr_required"),),
        source_kind="pdf",
    )
    monkeypatch.setattr(
        ocr.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ocr.subprocess.TimeoutExpired("render", 1)),
    )
    with pytest.raises(ocr.OCRError, match="渲染超时") as caught:
        ocr.recognize(b"pdf", extraction)
    assert caught.value.code == "ocr_render_timeout"


async def test_retryable_ocr_timeout_enters_finite_backoff(client, db_session, monkeypatch):
    ref = client._kap_storage.save(b"fake-image", original_name="scan.png")
    task = IngestTask(
        source="path_b_upload",
        source_file_ref=ref,
        source_file_name="scan.png",
        source_file_mime_type="image/png",
        source_file_size=10,
        status="processing",
        created_by=USER_CONSULTANT,
    )
    db_session.add(task)
    await db_session.commit()
    extraction = ExtractionResult(
        text="",
        status="ocr_required",
        error_type=None,
        error_message=None,
        char_count=0,
        pages=(ExtractionPage(1, "", "ocr_required"),),
        source_kind="image",
    )
    monkeypatch.setattr(ingest_processing, "extract_text", lambda *_args, **_kwargs: extraction)

    def timeout(*_args, **_kwargs):
        raise ocr.OCRError("ocr_page_timeout", "单页 OCR 超时。", retryable=True)

    monkeypatch.setattr(ingest_processing.ocr, "recognize", timeout)
    result = await ingest_processing.process_upload_task(
        db_session,
        task.id,
        storage=client._kap_storage,
        llm=client._kap_generation_llm,
        desensitizer=NullDesensitizer(),
        trace_id="ocr-timeout-recovery",
    )

    await db_session.refresh(task)
    assert result.startswith("ocr_retry_scheduled:")
    assert task.status == "processing"
    assert task.processing_stage == "processing_interrupted"
    assert task.retry_count == 1
    assert task.recovery_not_before is not None


async def test_compose_isolates_ocr_with_auditable_backpressure():
    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    assert "--queues=default" in compose
    assert "--queues=ocr" in compose
    assert "--pool=prefork" in compose
    assert "--concurrency=${OCR_WORKER_CONCURRENCY:-1}" in compose
    assert "--prefetch-multiplier=${OCR_WORKER_PREFETCH_MULTIPLIER:-1}" in compose
    assert "--max-tasks-per-child=${OCR_WORKER_MAX_TASKS_PER_CHILD:-4}" in compose
    assert "--max-memory-per-child=${OCR_WORKER_MAX_MEMORY_PER_CHILD_KB:-700000}" in compose

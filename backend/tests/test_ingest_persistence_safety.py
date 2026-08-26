from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

from sqlalchemy.exc import SQLAlchemyError

from app.models.ingest import IngestTask, IngestTaskAiResult
from app.seed.dev_seed import USER_CONSULTANT
from app.services.desensitization import NullDesensitizer
from app.services.jobs import ingest_processing
from app.services.llm_client import NullLLMClient
from app.services.storage import LocalFileStorage


def test_ai_result_database_boundary_sanitizes_text_and_json():
    task = IngestTask(
        id=uuid.uuid4(),
        ai_result=IngestTaskAiResult(
            duplicate_of_task_id=uuid.uuid4(), duplicate_of_asset_id=uuid.uuid4()
        ),
    )
    ingest_processing._apply_ai_result(
        task,
        {
            "suggested_title": "正常中文\x00\ud800标题",
            "suggested_summary": "第一行\r\n第二行\x01",
            "suggested_tags": ["安全\x00", b"binary"],
            "naming_parsed_fields": {"score": float("nan"), "payload": b"binary"},
        },
    )

    assert task.ai_result.suggested_title == "正常中文标题"
    assert task.ai_result.suggested_summary == "第一行\n第二行"
    assert task.ai_result.suggested_tags == ["安全"]
    assert task.ai_result.naming_parsed_fields == {"score": None, "payload": None}
    assert task.ai_result.duplicate_of_task_id is None
    assert task.ai_result.duplicate_of_asset_id is None


async def test_persistence_failure_rolls_back_before_terminal_state_and_usage(monkeypatch):
    events: list[str] = []
    session = AsyncMock()
    session.rollback.side_effect = lambda: events.append("rollback")
    session.execute.side_effect = lambda _statement: events.append("terminal_update")
    session.commit.side_effect = lambda: events.append("commit")

    async def record_usage(*_args, **kwargs):
        events.append(f"usage:{kwargs['outcome']}")

    monkeypatch.setattr(ingest_processing.llm_usage, "record", record_usage)
    status = await ingest_processing._terminalize_persistence_failure(
        session,
        task_id=uuid.uuid4(),
        provider="safe-provider",
        model="safe-model",
        model_attempted=True,
        failure_stage="content_result_persistence_failed",
    )

    assert status == "failed"
    assert events == ["rollback", "terminal_update", "usage:persistence_failure", "commit"]


async def test_intermediate_commit_failure_rolls_back_and_terminalizes(
    db_session, tmp_path, monkeypatch
):
    storage = LocalFileStorage(tmp_path / "persistence-store")
    ref = storage.save(b"safe text", original_name="early.txt")
    task = IngestTask(
        source="path_b_upload",
        source_file_ref=ref,
        source_file_name="early.txt",
        source_file_mime_type="text/plain",
        source_file_size=9,
        source_file_hash="early-hash",
        status="processing",
        created_by=USER_CONSULTANT,
    )
    db_session.add(task)
    await db_session.commit()
    task_id = task.id

    original_commit = db_session.commit
    original_rollback = db_session.rollback
    commit_calls = 0
    rollback_calls = 0

    async def fail_first_commit():
        nonlocal commit_calls
        commit_calls += 1
        if commit_calls == 1:
            raise SQLAlchemyError("simulated intermediate commit failure")
        await original_commit()

    async def track_rollback():
        nonlocal rollback_calls
        rollback_calls += 1
        await original_rollback()

    monkeypatch.setattr(db_session, "commit", fail_first_commit)
    monkeypatch.setattr(db_session, "rollback", track_rollback)

    status = await ingest_processing.process_upload_task(
        db_session,
        task_id,
        storage=storage,
        llm=NullLLMClient(),
        desensitizer=NullDesensitizer(),
        trace_id="intermediate-commit-failure",
    )

    persisted = await db_session.get(IngestTask, task_id)
    assert status == "failed"
    assert rollback_calls >= 1
    assert persisted.status == "failed"
    assert persisted.processing_stage == "processing_state_persistence_failed"
    assert persisted.error_type == "processing_state_persistence_failed"
    assert persisted.retry_count == 1

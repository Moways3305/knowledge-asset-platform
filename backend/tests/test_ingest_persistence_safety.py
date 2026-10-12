from __future__ import annotations

import uuid
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.models.ingest import IngestTask, IngestTaskAiResult
from app.seed.dev_seed import USER_CONSULTANT
from app.services import ingest
from app.services.desensitization import NullDesensitizer
from app.services.identity import load_user_with_roles
from app.services.jobs import ingest_processing
from app.services.llm_client import NullLLMClient
from app.services.permission import build_caller_context
from app.services.storage import LocalFileStorage


@pytest.mark.parametrize("committed", [False, True])
async def test_upload_commit_unknown_preserves_bytes(db_session, tmp_path, monkeypatch, committed):
    storage = LocalFileStorage(tmp_path / "ambiguous-store")
    user = await load_user_with_roles(db_session, user_id=USER_CONSULTANT)
    caller = build_caller_context(user)
    original_commit = db_session.commit

    async def ambiguous_commit():
        if committed:
            await original_commit()
        raise SQLAlchemyError("simulated acknowledgement lost")

    monkeypatch.setattr(db_session, "commit", ambiguous_commit)
    with pytest.raises(SQLAlchemyError, match="acknowledgement lost"):
        await ingest.create_upload(
            db_session,
            caller,
            content=b"source must survive ambiguous commit",
            file_name="ambiguous.txt",
            file_mime_type="text/plain",
            target_scope="personal",
            target_project_id=None,
            storage=storage,
            llm=NullLLMClient(),
            desensitizer=NullDesensitizer(),
            trace_id="commit-outcome-unknown",
        )
    files = [p for p in storage.root.rglob("*") if p.is_file()]
    assert len(files) == 1
    tasks = (
        await db_session.scalars(
            select(IngestTask).where(IngestTask.source_file_name == "ambiguous.txt")
        )
    ).all()
    assert bool(tasks) is committed
    if committed:
        assert storage.resolve_path(tasks[0].source_file_ref).is_file()
        from app.db.utils import utc_now
        from app.services.jobs.ingest_recovery import recover_stale_tasks

        monkeypatch.setattr(db_session, "commit", original_commit)
        summary = await recover_stale_tasks(
            db_session, storage=storage, now=utc_now() + timedelta(hours=2)
        )
        assert any(item.task_id == tasks[0].id for item in summary.scheduled)


async def test_upload_precommit_failure_deletes_unreferenced_bytes(
    db_session, tmp_path, monkeypatch
):
    storage = LocalFileStorage(tmp_path / "precommit-store")
    user = await load_user_with_roles(db_session, user_id=USER_CONSULTANT)
    caller = build_caller_context(user)
    monkeypatch.setattr(db_session, "flush", AsyncMock(side_effect=SQLAlchemyError("flush failed")))
    with pytest.raises(SQLAlchemyError, match="flush failed"):
        await ingest.create_upload(
            db_session,
            caller,
            content=b"precommit",
            file_name="precommit.txt",
            file_mime_type="text/plain",
            target_scope="personal",
            target_project_id=None,
            storage=storage,
            llm=NullLLMClient(),
            desensitizer=NullDesensitizer(),
            trace_id="precommit-failed",
        )
    assert not [p for p in storage.root.rglob("*") if p.is_file()]


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

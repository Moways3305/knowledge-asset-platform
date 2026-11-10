"""Content generation releases business transactions without releasing task ownership."""

import asyncio
import threading
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
import test_job_execution_postgres as jobs
from conftest import TestGenerationLLM
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from app.models.audit import AuditEvent
from app.models.identity import User
from app.models.ingest import IngestTask
from app.models.llm_usage import LLMUsageEvent
from app.schemas.enums import AuditAction
from app.services import generation_models
from app.services import storage as storage_service
from app.services.desensitization import NullDesensitizer
from app.services.job_execution import try_execution_lock
from app.services.jobs import ingest_processing
from app.worker import runtime
from app.worker.tasks import ingest as worker

job_db = jobs.job_db


@pytest_asyncio.fixture
async def bounded_job_db(job_db):
    original, storage = job_db
    async with original() as session:
        schema = await session.scalar(text("SELECT current_schema()"))
    engine = create_async_engine(
        original.kw["bind"].url,
        pool_size=2,
        max_overflow=0,
        pool_timeout=1,
        connect_args={"server_settings": {"search_path": schema}},
    )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False), storage
    finally:
        await engine.dispose()


async def test_model_wait_returns_business_connection_but_keeps_owner(bounded_job_db, monkeypatch):
    sessions, _ = bounded_job_db
    task_id, pending, _, release, calls = await jobs.start_upload(bounded_job_db, monkeypatch)
    try:
        async with sessions() as other:
            assert await asyncio.wait_for(other.scalar(text("SELECT 1")), 0.75) == 1
            assert not await try_execution_lock(other, "ingest", task_id)
        assert sessions.kw["bind"].pool.checkedout() == 1
    finally:
        release.set()
        await pending
    assert pending.result() == "pending_confirmation"
    assert len(calls) == 1
    assert sessions.kw["bind"].pool.checkedout() == 0


async def test_inline_caller_keeps_its_records_without_holding_model_transaction(job_db):
    sessions, storage = job_db
    async with sessions() as session:
        caller = await session.get(User, jobs.USER_CONSULTANT)
        task = IngestTask(
            source="path_a_wecom",
            source_file_ref=storage.save(b"synthetic inline caller", original_name="inline.md"),
            source_file_name="inline.md",
            source_file_mime_type="text/markdown",
            created_by=caller.id,
            status="processing",
        )
        session.add(task)
        await session.commit()

        class Model(TestGenerationLLM):
            async def chat_completion(self, *args, **kwargs):
                assert not session.in_transaction()
                assert caller in session
                return await super().chat_completion(*args, **kwargs)

        assert (
            await ingest_processing.process_upload_task(
                session,
                task.id,
                storage=storage,
                llm=Model(),
                desensitizer=NullDesensitizer(),
                trace_id="synthetic-inline",
            )
            == "pending_confirmation"
        )
        # Inline callers (including WeCom scanning) refresh their own records
        # after processing each file on this same session.
        await session.refresh(caller)
        assert caller.id == jobs.USER_CONSULTANT


async def result_state(sessions, task_id):
    async with sessions() as session:
        task = await session.scalar(
            select(IngestTask)
            .where(IngestTask.id == task_id)
            .options(
                selectinload(IngestTask.ai_result), selectinload(IngestTask.canonical_markdown)
            )
        )
        usage = list(await session.scalars(select(LLMUsageEvent.outcome)))
        audits = await session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.target_id == task_id,
                AuditEvent.action == AuditAction.ingest_ai_extracted.value,
            )
        )
        return task, usage, audits


@pytest.mark.parametrize("change", ["cancel", "lease", "terminal", "scope", "source"])
@pytest.mark.parametrize("failure", [False, True])
async def test_model_completion_rechecks_current_task(job_db, monkeypatch, change, failure):
    sessions, _ = job_db
    if failure:
        original = ingest_processing.content_processing.process_content

        async def fail(*args, **kwargs):
            await original(*args, **kwargs)
            raise SQLAlchemyError("synthetic persistence failure after model response")

        monkeypatch.setattr(ingest_processing.content_processing, "process_content", fail)
    task_id, pending, _, release, _ = await jobs.start_upload(job_db, monkeypatch)
    try:
        async with sessions() as session:
            task = await session.get(IngestTask, task_id)
            if change == "cancel":
                task.cancel_requested = True
            elif change == "lease":
                task.processing_job_id = "newer-message"
                task.processing_attempt += 1
            elif change == "terminal":
                task.status = "completed"
            elif change == "scope":
                task.target_scope = "personal"
            else:
                task.source_file_hash = "changed-source"
            await session.commit()
    finally:
        release.set()
        await pending
    task, usage, audits = await result_state(sessions, task_id)
    assert task.status == (
        "cancelled" if change == "cancel" else "completed" if change == "terminal" else "processing"
    )
    assert (task.ai_result.naming_parsed_fields or {}).get("generation_status") != "generated"
    assert task.canonical_markdown.status == "ready"
    assert usage == (["success"] if change == "cancel" and not failure else [])
    assert audits == 0
    if change == "lease":
        assert task.processing_job_id == "newer-message" and task.processing_attempt == 2


@pytest.mark.parametrize("failure", ["sql", "runtime", "cancel"])
async def test_final_write_failure_keeps_checkpoint_without_partial_result(
    job_db, monkeypatch, failure
):
    sessions, _ = job_db
    entered = asyncio.Event()
    original = ingest_processing.audit_service.record_event

    async def fail(session, **kwargs):
        await original(session, **kwargs)
        if kwargs["action"] == AuditAction.ingest_ai_extracted.value:
            # All generated content, usage and audit really reached PostgreSQL.
            await session.flush()
            entered.set()
            if failure == "cancel":
                await asyncio.Event().wait()
            raise (SQLAlchemyError if failure == "sql" else RuntimeError)(
                "synthetic final write failure"
            )

    monkeypatch.setattr(ingest_processing.audit_service, "record_event", fail)
    task_id, pending, _, release, _ = await jobs.start_upload(job_db, monkeypatch)
    try:
        release.set()
        await asyncio.wait_for(entered.wait(), 5)
        if failure == "cancel":
            pending.cancel()
        if failure == "sql":
            assert await pending == "failed"
        else:
            with pytest.raises(asyncio.CancelledError if failure == "cancel" else RuntimeError):
                await pending
    finally:
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
    task, usage, audits = await result_state(sessions, task_id)
    assert task.status == ("failed" if failure == "sql" else "processing")
    assert task.ai_result.extraction_status == "extracted"
    assert task.canonical_markdown.status == "ready"
    assert (task.ai_result.naming_parsed_fields or {}).get("generation_status") != "generated"
    assert usage == (["persistence_failure"] if failure == "sql" else [])
    assert audits == 0


async def test_lost_commit_ack_does_not_downgrade_committed_success(job_db, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession

    sessions, _ = job_db
    original, failed = AsyncSession.commit, False

    async def lose_ack(session):
        nonlocal failed
        final = any(
            isinstance(row, IngestTask) and row.status == "pending_confirmation"
            for row in session.identity_map.values()
        )
        await original(session)
        if final and not failed:
            failed = True
            raise SQLAlchemyError("synthetic acknowledgement lost after COMMIT")

    monkeypatch.setattr(AsyncSession, "commit", lose_ack)
    task_id, pending, _, release, calls = await jobs.start_upload(job_db, monkeypatch)
    release.set()
    assert await pending == "pending_confirmation"
    task, usage, audits = await result_state(sessions, task_id)
    assert failed and len(calls) == 1
    assert task.status == "pending_confirmation" and task.retry_count == 0
    assert (task.ai_result.naming_parsed_fields or {}).get("generation_status") == "generated"
    assert usage == ["success"] and audits == 1


async def test_cache_hit_and_redelivery_do_not_repeat_generation(job_db, monkeypatch):
    sessions, storage = job_db
    task_id, pending, _, release, calls = await jobs.start_upload(job_db, monkeypatch)
    release.set()
    assert await pending == "pending_confirmation"
    first, _, _ = await result_state(sessions, task_id)
    content = storage.resolve_path(first.source_file_ref).read_bytes()
    async with sessions() as session:
        second = IngestTask(
            source=first.source,
            source_file_ref=storage.save(content, original_name="copy.md"),
            source_file_name="copy.md",
            source_file_mime_type="text/markdown",
            source_file_size=len(content),
            created_by=first.created_by,
            status="processing",
        )
        session.add(second)
        await session.commit()
        second_id = second.id
    for _ in range(2):
        assert (
            await worker._run(sessions, str(second_id), "synthetic-cache", "worker-b", "message-2")
            == "pending_confirmation"
        )
    second, usage, audits = await result_state(sessions, second_id)
    assert len(calls) == 1 and sorted(usage) == ["cache_hit", "success"]
    assert audits == 1 and second.processing_attempt == 1
    assert second.ai_result.id != first.ai_result.id


@pytest.mark.parametrize("cancel", [False, True])
async def test_real_ingest_runtime_retains_only_owner_connection(job_db, monkeypatch, cancel):
    sessions, storage = job_db
    entered, release = threading.Event(), threading.Event()
    tag = "kap-ingest-" + uuid.uuid4().hex
    async with sessions() as session:
        schema = await session.scalar(text("SELECT current_schema()"))
        task = IngestTask(
            source="path_b_upload",
            source_file_ref=storage.save(b"synthetic runtime material", original_name="runtime.md"),
            source_file_name="runtime.md",
            source_file_mime_type="text/markdown",
            created_by=jobs.USER_CONSULTANT,
            status="processing",
        )
        session.add(task)
        await session.commit()
        task_id = task.id

    def engine(url, **options):
        return create_async_engine(
            url,
            **options,
            connect_args={
                "server_settings": {
                    "search_path": schema,
                    "application_name": tag,
                }
            },
        )

    class Model(TestGenerationLLM):
        async def chat_completion(self, *args, **kwargs):
            entered.set()
            await asyncio.to_thread(release.wait)
            if cancel:
                raise asyncio.CancelledError()
            return await super().chat_completion(*args, **kwargs)

    async def resolve(_session):
        return Model()

    monkeypatch.setattr(runtime, "create_async_engine", engine)
    monkeypatch.setattr(
        runtime, "get_settings", lambda: SimpleNamespace(database_url=sessions.kw["bind"].url)
    )
    monkeypatch.setattr(generation_models, "resolve_generation_llm_client", resolve)
    monkeypatch.setattr(storage_service, "get_storage", lambda: storage)
    pending = asyncio.create_task(
        asyncio.to_thread(worker.process_ingest_upload.run, str(task_id), "synthetic-runtime")
    )
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        async with sessions() as observer:
            assert (
                await observer.scalar(
                    text("SELECT count(*) FROM pg_stat_activity WHERE application_name=:tag"),
                    {"tag": tag},
                )
                == 1
            )
            assert not await try_execution_lock(observer, "ingest", task_id)
        release.set()
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await pending
        else:
            await pending
        async with sessions() as observer:
            assert (
                await observer.scalar(
                    text("SELECT count(*) FROM pg_stat_activity WHERE application_name=:tag"),
                    {"tag": tag},
                )
                == 0
            )
            assert await try_execution_lock(observer, "ingest", task_id)
        task, usage, audits = await result_state(sessions, task_id)
        assert task.status == ("processing" if cancel else "pending_confirmation")
        assert usage == ([] if cancel else ["success"])
        assert audits == (0 if cancel else 1)
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)

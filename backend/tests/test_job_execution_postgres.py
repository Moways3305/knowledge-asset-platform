"""Real independent transactions for duplicate deliveries and stale upstream results."""

import asyncio
import os
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from conftest import TestGenerationLLM
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.utils import utc_now
from app.models.indexing_job import IndexingOperationJob
from app.models.ingest import IngestTask
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.seed.dev_seed import (
    KA_COMPANY_L2,
    USER_BOSS,
    USER_CONSULTANT,
    seed_dev_identities,
    seed_dev_knowledge,
)
from app.services import indexing, knowledge_lifecycle
from app.services.desensitization import NullDesensitizer
from app.services.identity import load_user_with_roles
from app.services.job_execution import try_execution_lock
from app.services.jobs import indexing_operations, ingest_processing, ingest_recovery
from app.services.jobs.ingest_cancellation import cleanup_cancelled_tasks
from app.services.permission import build_caller_context
from app.services.storage import LocalFileStorage
from app.services.weknora_client import WeKnoraDuplicateError, WeKnoraError
from app.worker.tasks import ingest as worker


@pytest_asyncio.fixture
async def job_db(tmp_path):
    url = os.environ.get("KAP_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("KAP_TEST_POSTGRES_URL is required for concurrent worker verification")
    assert url.startswith("postgresql+asyncpg://")
    schema = "kap_jobs_" + uuid.uuid4().hex
    admin = create_async_engine(url)
    engine = create_async_engine(
        url,
        connect_args={"server_settings": {"search_path": schema, "statement_timeout": "5000"}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            await seed_dev_identities(session)
            await seed_dev_knowledge(session)
        yield sessions, LocalFileStorage(tmp_path / "synthetic-files")
    finally:
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def start_upload(job_db, monkeypatch):
    sessions, storage = job_db
    content = "# 合成资料\n\n仅用于并发测试的正文。".encode()
    async with sessions() as setup:
        task = IngestTask(
            source="path_b_upload",
            source_file_ref=storage.save(content, original_name="synthetic.md"),
            source_file_name="synthetic.md",
            source_file_mime_type="text/markdown",
            source_file_size=len(content),
            created_by=USER_CONSULTANT,
            status="processing",
        )
        setup.add(task)
        await setup.commit()
        task_id = task.id

    entered, duplicate, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []

    class Model(TestGenerationLLM):
        async def chat_completion(self, *args, **kwargs):
            calls.append(1)
            (entered if len(calls) == 1 else duplicate).set()
            await release.wait()
            return await super().chat_completion(*args, **kwargs)

    async def process(maker, task_id_str, trace_id, worker_id, job_id):
        async with maker() as session:
            return await ingest_processing.process_upload_task(
                session,
                uuid.UUID(task_id_str),
                storage=storage,
                llm=Model(),
                desensitizer=NullDesensitizer(),
                trace_id=trace_id,
                worker_id=worker_id,
                job_id=job_id,
            )

    monkeypatch.setattr(worker, "_process", process)
    first = asyncio.create_task(
        worker._run(sessions, str(task_id), "synthetic-ingest", "worker-a", "message-1")
    )
    await asyncio.wait_for(entered.wait(), timeout=5)
    return task_id, first, duplicate, release, calls


@pytest.mark.parametrize("message_id", ["message-1", "another-message"])
async def test_duplicate_delivery_does_not_repeat_model(job_db, monkeypatch, message_id):
    sessions, _ = job_db
    task_id, first, duplicate, release, calls = await start_upload(job_db, monkeypatch)
    second = asyncio.create_task(
        worker._run(sessions, str(task_id), "synthetic-ingest", "worker-b", message_id)
    )
    observed = asyncio.create_task(duplicate.wait())
    try:
        done, _ = await asyncio.wait(
            {second, observed}, timeout=3, return_when=asyncio.FIRST_COMPLETED
        )
        assert done
        assert not duplicate.is_set(), "one upload was sent to the model concurrently twice"
        await second
    finally:
        release.set()
        observed.cancel()
        await asyncio.gather(first, second, observed, return_exceptions=True)
    assert first.result() == "pending_confirmation"
    assert len(calls) == 1
    async with sessions() as check:
        task = await check.get(IngestTask, task_id)
        assert task.processing_attempt == 1


async def test_recovery_cannot_take_a_live_worker_lease(job_db, monkeypatch):
    sessions, storage = job_db
    task_id, first, _, release, _ = await start_upload(job_db, monkeypatch)
    try:
        async with sessions() as scan:
            summary = await ingest_recovery.recover_stale_tasks(
                scan, storage, now=utc_now() + timedelta(hours=1), task_ids=(task_id,)
            )
            assert not summary.scheduled, "a slow live worker must not be recovered as dead"
    finally:
        release.set()
        await first
    async with sessions() as check:
        task = await check.get(IngestTask, task_id)
        assert task.retry_count == 0
        assert task.status == "pending_confirmation"


async def test_interrupted_upload_can_resume_once(job_db, monkeypatch):
    sessions, storage = job_db
    task_id, first, _, release, calls = await start_upload(job_db, monkeypatch)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    async with sessions() as scan:
        summary = await ingest_recovery.recover_stale_tasks(
            scan, storage, now=utc_now() + timedelta(hours=1), task_ids=(task_id,)
        )
        assert [item.task_id for item in summary.scheduled] == [task_id]
    release.set()
    result = await worker._run(sessions, str(task_id), "resumed", "worker-new", "message-new")
    assert result == "pending_confirmation"
    assert len(calls) == 2  # One interrupted call, one recovery; no duplicate success.
    async with sessions() as check:
        task = await check.get(IngestTask, task_id)
        assert task.processing_attempt == 2
        assert task.retry_count == 1
    assert (
        await worker._run(sessions, str(task_id), "replay", "worker-new", "message-new")
        == "pending_confirmation"
    )
    assert len(calls) == 2


async def test_cancellation_cleanup_waits_for_worker_exit(job_db, monkeypatch):
    sessions, storage = job_db
    task_id, first, _, release, _ = await start_upload(job_db, monkeypatch)
    try:
        async with sessions() as change:
            task = await change.get(IngestTask, task_id)
            source = task.source_file_ref
            task.cancel_requested = True
            task.status = "cancelled"
            await change.commit()
        async with sessions() as scan:
            assert await cleanup_cancelled_tasks(scan, storage, task_ids=(task_id,)) == 0
        assert storage.exists(source)
    finally:
        release.set()
        await first
    assert first.result() == "cancelled"
    async with sessions() as scan:
        assert await cleanup_cancelled_tasks(scan, storage, task_ids=(task_id,)) == 1
    assert not storage.exists(source)


async def test_concurrent_index_and_reparse_send_one_request(job_db, monkeypatch):
    sessions, _ = job_db
    entered, repeated, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []

    class Foundation:
        async def reparse_knowledge(self, **kwargs):
            calls.append(1)
            (entered if len(calls) == 1 else repeated).set()
            await release.wait()
            return {"id": "synthetic-index-doc", "parse_status": "completed"}

        upload_file = reparse_knowledge

    monkeypatch.setattr(indexing, "resolve_models_for_kb", AsyncMock(return_value={}))
    monkeypatch.setattr(indexing, "resolve_or_create_kb", AsyncMock(return_value="wk-kb-company"))
    async with sessions() as setup:
        asset = await setup.get(KnowledgeAsset, KA_COMPANY_L2)
        version_id = asset.current_version_id

    async def run(operation):
        async with sessions() as session:
            return await operation(
                session,
                Foundation(),
                asset_id=KA_COMPANY_L2,
                version_id=version_id,
                scope="company",
                owner_user_id=USER_CONSULTANT,
                project_id=None,
                confidentiality="L2",
                file_bytes=b"# Synthetic fixture",
                source_file_name="synthetic.canonical.md",
                source_file_mime="text/markdown",
                channel=None,
                trace_id="synthetic-index-lock",
            )

    first = asyncio.create_task(run(indexing.reparse_asset_version))
    await asyncio.wait_for(entered.wait(), timeout=5)
    second = asyncio.create_task(run(indexing.index_asset_version))
    observed = asyncio.create_task(repeated.wait())
    try:
        done, _ = await asyncio.wait(
            {second, observed}, timeout=3, return_when=asyncio.FIRST_COMPLETED
        )
        assert done and not repeated.is_set()
        assert (await second).index_status == "indexing"
    finally:
        release.set()
        observed.cancel()
        await asyncio.gather(first, second, observed, return_exceptions=True)
    assert first.result().index_status == "indexed"
    assert len(calls) == 1


async def test_index_job_duplicate_does_not_replay_targets(job_db, monkeypatch):
    sessions, storage = job_db
    entered, repeated, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []
    async with sessions() as setup:
        asset = await setup.get(KnowledgeAsset, KA_COMPANY_L2)
        version = await setup.get(KnowledgeAssetVersion, asset.current_version_id)
        version.index_status = "index_failed"
        job = IndexingOperationJob(
            operation_type="retry_index",
            status="queued",
            target_asset_id=asset.id,
            requested_by_user_id=USER_BOSS,
            trace_id="synthetic-index-job",
        )
        setup.add(job)
        await setup.commit()
        job_id = job.id

    async def process(*args, **kwargs):
        calls.append(1)
        (entered if len(calls) == 1 else repeated).set()
        await release.wait()
        return "indexed"

    monkeypatch.setattr(indexing_operations, "_process_one", process)
    monkeypatch.setattr(indexing_operations, "enqueue_outbox_delivery", AsyncMock())

    async def run():
        async with sessions() as session:
            return await indexing_operations.run_operation_job(
                session, job_id, weknora=None, storage=storage
            )

    first = asyncio.create_task(run())
    await asyncio.wait_for(entered.wait(), timeout=5)
    second = asyncio.create_task(run())
    observed = asyncio.create_task(repeated.wait())
    try:
        done, _ = await asyncio.wait(
            {second, observed}, timeout=3, return_when=asyncio.FIRST_COMPLETED
        )
        assert done and not repeated.is_set()
        assert await second == "running"
    finally:
        release.set()
        observed.cancel()
        await asyncio.gather(first, second, observed, return_exceptions=True)
    assert first.result() == "completed"
    assert await run() == "completed"
    assert len(calls) == 1


async def test_stopped_index_jobs_recover_without_stealing_live_work(job_db, monkeypatch):
    sessions, _ = job_db
    monkeypatch.setattr(indexing_operations, "enqueue_outbox_delivery", AsyncMock())
    async with sessions() as setup:
        jobs = [
            IndexingOperationJob(
                operation_type="reparse",
                status="running",
                requested_by_user_id=USER_BOSS,
                started_at=utc_now() - timedelta(hours=1),
                trace_id=f"recovery-{index}",
            )
            for index in range(2)
        ]
        setup.add_all(jobs)
        await setup.commit()
        live_id, stopped_id = [job.id for job in jobs]
    async with sessions() as owner:
        assert await try_execution_lock(owner, "index-job", live_id)
        async with sessions() as scan:
            assert await indexing_operations.recover_interrupted_jobs(scan) == 1
        async with sessions() as check:
            assert (await check.get(IndexingOperationJob, live_id)).status == "running"
            assert (
                await check.get(IndexingOperationJob, stopped_id)
            ).error_code == "index_job_interrupted"
        # Close the actual owner connection, as on process loss. Its lock must
        # disappear even though the durable job still says running.
        connection = await owner.connection()
        await connection.invalidate()
        await owner.rollback()
    async with sessions() as scan:
        assert await indexing_operations.recover_interrupted_jobs(scan) == 1
        assert await indexing_operations.recover_interrupted_jobs(scan) == 0


@pytest.mark.parametrize("mutation", ["delete", "supersede"])
@pytest.mark.parametrize("operation_name", ["index_asset_version", "reparse_asset_version"])
@pytest.mark.parametrize("provider_result", ["success", "duplicate", "failure"])
async def test_index_result_does_not_restore_a_terminal_version(
    job_db, monkeypatch, mutation, operation_name, provider_result
):
    sessions, _ = job_db
    entered, release = asyncio.Event(), asyncio.Event()
    deleted = []

    class Foundation:
        async def reparse_knowledge(self, **kwargs):
            entered.set()
            await release.wait()
            if provider_result == "duplicate":
                raise WeKnoraDuplicateError("synthetic-new-document")
            if provider_result == "failure":
                raise WeKnoraError("weknora_call_failed", "synthetic failure")
            return {"id": "synthetic-new-document", "parse_status": "completed"}

        upload_file = reparse_knowledge

        async def delete_knowledge(self, knowledge_id, **kwargs):
            deleted.append(knowledge_id)

    monkeypatch.setattr(indexing, "resolve_models_for_kb", AsyncMock(return_value={}))
    monkeypatch.setattr(indexing, "resolve_or_create_kb", AsyncMock(return_value="wk-kb-company"))
    async with sessions() as setup:
        asset = await setup.get(KnowledgeAsset, KA_COMPANY_L2)
        version_id = asset.current_version_id
    async with sessions() as work:
        operation = asyncio.create_task(
            getattr(indexing, operation_name)(
                work,
                Foundation(),
                asset_id=KA_COMPANY_L2,
                version_id=version_id,
                scope="company",
                owner_user_id=USER_CONSULTANT,
                project_id=None,
                confidentiality="L2",
                file_bytes=b"# synthetic\n\nOnly fixture content.",
                source_file_name="synthetic.canonical.md",
                source_file_mime="text/markdown",
                channel=None,
                trace_id="synthetic-terminal-test",
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            async with sessions() as change:
                if mutation == "delete":
                    user = await load_user_with_roles(change, user_id=USER_BOSS)
                    await knowledge_lifecycle.delete_asset(
                        change,
                        build_caller_context(user),
                        KA_COMPANY_L2,
                        reason="synthetic concurrent deletion",
                        weknora=Foundation(),
                        trace_id="synthetic-delete",
                        weknora_is_enabled=lambda: True,
                    )
                else:
                    old = await change.get(KnowledgeAssetVersion, version_id)
                    old.version_status = "superseded"
                    await change.flush()
                    new = KnowledgeAssetVersion(
                        asset_id=KA_COMPANY_L2,
                        version_no="v-next",
                        version_status="active",
                        created_by=USER_CONSULTANT,
                    )
                    change.add(new)
                    await change.flush()
                    asset = await change.get(KnowledgeAsset, KA_COMPANY_L2)
                    asset.current_version_id = new.id
                    await change.commit()
        finally:
            release.set()
            outcome = await operation
    async with sessions() as check:
        version = await check.get(KnowledgeAssetVersion, version_id)
        assert version.weknora_doc_id != "synthetic-new-document"
        assert outcome.index_status == "skipped"
        assert ("synthetic-new-document" in deleted) == (provider_result == "success")

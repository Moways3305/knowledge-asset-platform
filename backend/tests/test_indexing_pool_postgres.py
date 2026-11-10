"""Real PostgreSQL boundaries for slow indexing and concurrent KB provisioning."""

import asyncio
import threading
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import test_job_execution_postgres as jobs
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.identity import Project, User
from app.models.indexing_job import IndexingOperationJob
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.weknora import WeknoraKbMapping
from app.services import canonical_markdown, indexing, weknora_client, weknora_defaults, weknora_kb
from app.services import storage as storage_service
from app.services.job_execution import try_execution_lock
from app.services.jobs import indexing_operations
from app.services.weknora_client import WeKnoraError
from app.services.weknora_model_selection import ResolvedModels, resolve_models_for_kb
from app.worker import runtime
from app.worker.tasks import indexing as index_worker

job_db = jobs.job_db


class Foundation:
    async def create_kb(self, **kwargs):
        return "synthetic-new-kb"

    async def list_models(self, **kwargs):
        return [
            {
                "id": "synthetic-embedding",
                "name": "text-embedding-v3",
                "type": "Embedding",
                "source": "remote",
            },
            {
                "id": "synthetic-chat",
                "name": "qwen-plus",
                "type": "KnowledgeQA",
                "source": "remote",
            },
        ]

    async def get_kb(self, kb_id, **kwargs):
        return {
            "id": kb_id,
            "summary_model_id": "synthetic-chat",
            "embedding_model_id": "synthetic-embedding",
        }

    async def update_initialization_config(self, kb_id, **kwargs):
        return {}

    async def upload_file(self, **kwargs):
        return {"id": "synthetic-new-doc", "parse_status": "completed"}

    reparse_knowledge = upload_file


def models():
    return ResolvedModels("synthetic-embedding", False, chat_model_id="synthetic-chat")


async def test_model_listing_ends_business_transaction(job_db):
    sessions, _ = job_db
    async with sessions() as session:
        await weknora_defaults.set_defaults(
            session,
            embedding_model_id="synthetic-embedding",
            chat_model_id="synthetic-chat",
            rerank_model_id=None,
            multimodal_id=None,
            updated_by=None,
        )
        await session.commit()

        class Slow(Foundation):
            async def list_models(self, **kwargs):
                assert not session.in_transaction(), (
                    "model discovery retains a business transaction"
                )
                return await super().list_models(**kwargs)

        await resolve_models_for_kb(
            session, Slow(), embedding_model_ref=None, rerank_model_ref=None, trace_id=None
        )
        assert not session.in_transaction()


@pytest.mark.parametrize("scope", ["personal", "company", "project"])
async def test_concurrent_scope_creates_one_remote_kb(job_db, scope):
    sessions, _ = job_db
    async with sessions() as setup:
        await setup.execute(delete(WeknoraKbMapping))
        project = await setup.scalar(select(Project.id).limit(1))
        await setup.commit()
    entered, release, repeated = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = []

    class Slow(Foundation):
        async def create_kb(self, **kwargs):
            calls.append(1)
            result = f"synthetic-kb-{len(calls)}"
            (entered if len(calls) == 1 else repeated).set()
            await release.wait()
            return result

    async def run():
        async with sessions() as session:
            return await weknora_kb.resolve_or_create_kb(
                session,
                Slow(),
                scope=scope,
                owner_user_id=jobs.USER_CONSULTANT if scope == "personal" else None,
                project_id=project if scope == "project" else None,
                models=models(),
                trace_id="synthetic-concurrent",
            )

    first = asyncio.create_task(run())
    await asyncio.wait_for(entered.wait(), 5)
    second = asyncio.create_task(run())
    observed = asyncio.create_task(repeated.wait())
    try:
        await asyncio.wait({second, observed}, timeout=0.4, return_when=asyncio.FIRST_COMPLETED)
        assert not repeated.is_set(), (
            "concurrent first use created a second upstream knowledge base"
        )
    finally:
        release.set()
        observed.cancel()
        await asyncio.gather(first, second, observed, return_exceptions=True)
    assert first.result() == second.result() and len(calls) == 1
    async with sessions() as session:
        assert (
            len(
                list(
                    await session.scalars(
                        select(WeknoraKbMapping).where(WeknoraKbMapping.scope == scope)
                    )
                )
            )
            == 1
        )


@pytest.mark.parametrize("stage", ["create", "initialize"])
async def test_provisioning_remote_wait_has_no_business_transaction(job_db, stage):
    sessions, _ = job_db
    async with sessions() as session:

        class Slow(Foundation):
            async def create_kb(self, **kwargs):
                if stage == "create":
                    assert not session.in_transaction(), (
                        "KB creation retains a business transaction"
                    )
                return "synthetic-new-kb"

            async def update_initialization_config(self, kb_id, **kwargs):
                if stage == "initialize":
                    assert not session.in_transaction(), (
                        "KB initialization retains a business transaction"
                    )
                return {}

        await weknora_kb.resolve_or_create_kb(
            session,
            Slow(),
            scope="personal",
            owner_user_id=jobs.USER_CONSULTANT,
            project_id=None,
            models=models(),
            trace_id="synthetic-boundary",
        )


async def test_scope_waiters_leave_pool_space_for_owner_to_finish(job_db):
    sessions, _ = job_db
    async with sessions() as observer:
        schema = await observer.scalar(text("SELECT current_schema()"))
    engine = create_async_engine(
        sessions.kw["bind"].url,
        pool_size=2,
        max_overflow=0,
        pool_timeout=1,
        connect_args={"server_settings": {"search_path": schema}},
    )
    bounded = async_sessionmaker(engine, expire_on_commit=False)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    class Slow(Foundation):
        async def create_kb(self, **kwargs):
            calls.append(1)
            entered.set()
            await release.wait()
            return "synthetic-bounded-kb"

    async def run():
        async with bounded() as session:
            return await provision(session, Slow())

    first = asyncio.create_task(run())
    pending = [first]
    try:
        await asyncio.wait_for(entered.wait(), 5)
        pending.extend(asyncio.create_task(run()) for _ in range(6))
        await asyncio.sleep(0.2)
        release.set()
        results = await asyncio.wait_for(asyncio.gather(*pending), 5)
        assert set(results) == {"synthetic-bounded-kb"} and len(calls) == 1
        assert engine.pool.checkedout() == 0
    finally:
        release.set()
        await asyncio.gather(*pending, return_exceptions=True)
        await engine.dispose()


async def provision(session, client):
    return await weknora_kb.resolve_or_create_kb(
        session,
        client,
        scope="personal",
        owner_user_id=jobs.USER_CONSULTANT,
        project_id=None,
        models=models(),
        trace_id="synthetic-provision",
    )


@pytest.mark.parametrize("failure", ["timeout", "cancel"])
async def test_interrupted_initialization_reuses_journalled_kb(job_db, failure):
    sessions, _ = job_db
    calls = []

    class Counting(Foundation):
        async def create_kb(self, **kwargs):
            calls.append(1)
            return await super().create_kb(**kwargs)

    class Broken(Counting):
        async def update_initialization_config(self, kb_id, **kwargs):
            if failure == "cancel":
                raise asyncio.CancelledError()
            raise httpx.ReadTimeout("synthetic timeout")

    async with sessions() as session:
        with pytest.raises(asyncio.CancelledError if failure == "cancel" else httpx.ReadTimeout):
            await provision(session, Broken())
    async with sessions() as check:
        row = await check.scalar(
            select(WeknoraKbMapping).where(WeknoraKbMapping.scope == "personal")
        )
        assert row.status == "init_failed" and row.weknora_kb_id == "synthetic-new-kb"
    async with sessions() as retry:
        assert await asyncio.wait_for(provision(retry, Counting()), 2) == "synthetic-new-kb"
        row = await retry.scalar(
            select(WeknoraKbMapping).where(WeknoraKbMapping.scope == "personal")
        )
        assert row.status == "active"
    assert len(calls) == 1


@pytest.mark.parametrize("change", ["migrating", "replace", "delete"])
async def test_initializer_does_not_restore_changed_mapping(job_db, change):
    sessions, _ = job_db

    class Changed(Foundation):
        async def update_initialization_config(self, kb_id, **kwargs):
            async with sessions() as other:
                row = await other.scalar(
                    select(WeknoraKbMapping).where(WeknoraKbMapping.scope == "personal")
                )
                if change == "delete":
                    await other.delete(row)
                elif change == "replace":
                    row.weknora_kb_id = "synthetic-replacement"
                else:
                    row.status = "migrating"
                await other.commit()

    async with sessions() as session:
        with pytest.raises(WeKnoraError) as raised:
            await provision(session, Changed())
        assert raised.value.code == "weknora_configuration_changed"
    async with sessions() as check:
        row = await check.scalar(
            select(WeknoraKbMapping).where(WeknoraKbMapping.scope == "personal")
        )
        if change == "delete":
            assert row is None
        elif change == "replace":
            assert row.weknora_kb_id == "synthetic-replacement" and row.status == "init_failed"
        else:
            assert row.status == "migrating"


async def test_scope_wait_is_bounded_and_cancel_safe(job_db, monkeypatch):
    sessions, _ = job_db
    entered, release = asyncio.Event(), asyncio.Event()

    class Held(Foundation):
        async def create_kb(self, **kwargs):
            entered.set()
            await release.wait()
            return await super().create_kb(**kwargs)

    async def run(client):
        async with sessions() as session:
            return await provision(session, client)

    first = asyncio.create_task(run(Held()))
    await asyncio.wait_for(entered.wait(), 3)
    monkeypatch.setattr(weknora_kb, "get_settings", lambda: SimpleNamespace(weknora_timeout=0.1))
    try:
        with pytest.raises(WeKnoraError) as raised:
            await asyncio.wait_for(run(Foundation()), 1)
        assert raised.value.code == "weknora_kb_busy"
        pending = asyncio.create_task(run(Foundation()))
        await asyncio.sleep(0.02)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        # Another scope can provision despite the blocked personal initializer.
        async with sessions() as other:
            result = await weknora_kb.resolve_or_create_kb(
                other,
                Foundation(),
                scope="personal",
                owner_user_id=jobs.USER_BOSS,
                project_id=None,
                models=models(),
                trace_id=None,
            )
            assert result == "synthetic-new-kb"
    finally:
        release.set()
        await first
    assert await run(Foundation()) == first.result()


async def seed_index(sessions, *, missing_kb=False):
    async with sessions() as session:
        await weknora_defaults.set_defaults(
            session,
            embedding_model_id="synthetic-embedding",
            chat_model_id="synthetic-chat",
            rerank_model_id=None,
            multimodal_id=None,
            updated_by=None,
        )
        if missing_kb:
            await session.execute(delete(WeknoraKbMapping))
        asset = await session.get(KnowledgeAsset, jobs.KA_COMPANY_L2)
        version = await session.get(KnowledgeAssetVersion, asset.current_version_id)
        version.index_status = "index_failed"
        version.weknora_parse_status = "failed"
        version.weknora_doc_id = None
        version.weknora_kb_id = None
        version_id = version.id
        await session.commit()
        return version_id


@pytest.mark.parametrize("stage", ["models", "create", "initialize", "upload", "reparse"])
async def test_indexing_releases_small_pool_and_preserves_caller(job_db, stage):
    original, _ = job_db
    version_id = await seed_index(original, missing_kb=stage in {"create", "initialize"})
    async with original() as session:
        schema = await session.scalar(text("SELECT current_schema()"))
    engine = create_async_engine(
        original.kw["bind"].url,
        pool_size=3,
        max_overflow=0,
        pool_timeout=1,
        connect_args={"server_settings": {"search_path": schema}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    entered, release = asyncio.Event(), asyncio.Event()

    class Slow(Foundation):
        async def pause(self, point):
            if point == stage:
                assert not work.in_transaction()
                assert caller in work
                entered.set()
                await release.wait()

        async def list_models(self, **kwargs):
            await self.pause("models")
            return await super().list_models(**kwargs)

        async def create_kb(self, **kwargs):
            await self.pause("create")
            return await super().create_kb(**kwargs)

        async def update_initialization_config(self, *args, **kwargs):
            await self.pause("initialize")
            return {}

        async def upload_file(self, **kwargs):
            await self.pause("upload")
            return await super().upload_file(**kwargs)

        async def reparse_knowledge(self, **kwargs):
            await self.pause("reparse")
            return await super().upload_file(**kwargs)

    try:
        async with sessions() as work:
            caller = await work.get(User, jobs.USER_CONSULTANT)
            operation = (
                indexing.reparse_asset_version
                if stage == "reparse"
                else indexing.index_asset_version
            )
            pending = asyncio.create_task(
                operation(
                    work,
                    Slow(),
                    asset_id=jobs.KA_COMPANY_L2,
                    version_id=version_id,
                    scope="company",
                    owner_user_id=None,
                    project_id=None,
                    confidentiality="L2",
                    file_bytes=b"# synthetic indexing\n\nOnly synthetic material.",
                    source_file_name="test.canonical.md",
                    source_file_mime="text/markdown",
                    channel=None,
                    trace_id=None,
                )
            )
            try:
                await asyncio.wait_for(entered.wait(), 5)
                async with sessions() as other:
                    assert await asyncio.wait_for(other.scalar(text("SELECT 1")), 0.75) == 1
                    assert not await try_execution_lock(other, "index-version", version_id)
                assert engine.pool.checkedout() == (2 if stage in {"create", "initialize"} else 1)
            finally:
                release.set()
                await pending
            assert pending.result().index_status == "indexed"
            await work.refresh(caller)
        assert engine.pool.checkedout() == 0
    finally:
        await engine.dispose()


async def test_model_defaults_changed_during_inventory_are_not_used(job_db):
    sessions, _ = job_db
    await seed_index(sessions)

    class Changed(Foundation):
        async def list_models(self, **kwargs):
            async with sessions() as other:
                await weknora_defaults.set_defaults(
                    other,
                    embedding_model_id="another-embedding",
                    chat_model_id="synthetic-chat",
                    rerank_model_id=None,
                    multimodal_id=None,
                    updated_by=None,
                )
                await other.commit()
            return await super().list_models(**kwargs)

    async with sessions() as work:
        with pytest.raises(WeKnoraError) as raised:
            await resolve_models_for_kb(
                work, Changed(), embedding_model_ref=None, rerank_model_ref=None, trace_id=None
            )
        assert raised.value.code == "weknora_configuration_changed"
        assert not work.in_transaction()


@pytest.mark.parametrize("stage", ["models", "initialize", "upload"])
async def test_real_index_worker_keeps_only_ownership_connections(job_db, monkeypatch, stage):
    sessions, storage = job_db
    version_id = await seed_index(sessions, missing_kb=stage == "initialize")
    entered, release = threading.Event(), threading.Event()
    tag = "kap-index-" + uuid.uuid4().hex
    async with sessions() as session:
        schema = await session.scalar(text("SELECT current_schema()"))
        job = IndexingOperationJob(
            operation_type="retry_index",
            status="queued",
            requested_by_user_id=jobs.USER_BOSS,
            target_asset_id=jobs.KA_COMPANY_L2,
            scope_filter={"limit": 1},
            trace_id="synthetic-physical-connections",
        )
        session.add(job)
        await session.commit()
        job_id = job.id

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

    class Slow(Foundation):
        async def pause(self, point):
            if point == stage:
                entered.set()
                await asyncio.to_thread(release.wait)

        async def list_models(self, **kwargs):
            await self.pause("models")
            return await super().list_models(**kwargs)

        async def update_initialization_config(self, *args, **kwargs):
            await self.pause("initialize")
            return {}

        async def upload_file(self, **kwargs):
            await self.pause("upload")
            return await super().upload_file(**kwargs)

    monkeypatch.setattr(runtime, "create_async_engine", engine)
    monkeypatch.setattr(
        runtime, "get_settings", lambda: SimpleNamespace(database_url=sessions.kw["bind"].url)
    )
    monkeypatch.setattr(storage_service, "get_storage", lambda: storage)
    monkeypatch.setattr(weknora_client, "get_weknora_client", lambda: Slow())
    monkeypatch.setattr(indexing_operations, "weknora_enabled", lambda: True)
    monkeypatch.setattr(indexing_operations, "enqueue_outbox_delivery", AsyncMock())
    monkeypatch.setattr(
        canonical_markdown,
        "ensure_version_markdown",
        AsyncMock(
            return_value=SimpleNamespace(
                content=b"# synthetic indexing",
                file_name="test.canonical.md",
                mime="text/markdown",
                channel=None,
            )
        ),
    )
    pending = asyncio.create_task(
        asyncio.to_thread(index_worker.run_indexing_operation.run, str(job_id))
    )
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        async with sessions() as observer:
            assert await observer.scalar(
                text("SELECT count(*) FROM pg_stat_activity WHERE application_name=:tag"),
                {"tag": tag},
            ) == (3 if stage == "initialize" else 2)
            assert not await try_execution_lock(observer, "index-job", job_id)
            assert not await try_execution_lock(observer, "index-version", version_id)
        release.set()
        await pending
        async with sessions() as observer:
            assert (
                await observer.scalar(
                    text("SELECT count(*) FROM pg_stat_activity WHERE application_name=:tag"),
                    {"tag": tag},
                )
                == 0
            )
            row = await observer.get(IndexingOperationJob, job_id)
            assert row.status == "completed" and row.success_count == 1
            assert await try_execution_lock(observer, "index-job", job_id)
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)

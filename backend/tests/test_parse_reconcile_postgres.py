"""Real PostgreSQL fairness, bounded reconciliation and worker ownership checks."""

import asyncio
import threading
import uuid
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
import test_job_execution_postgres as jobs
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.utils import utc_now
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.services import weknora_client
from app.services.jobs import parse_reconcile
from app.worker import runtime
from app.worker.tasks import parse as parse_worker

job_db = jobs.job_db


async def seed_pending(sessions, count):
    ids = []
    async with sessions() as session:
        for i in range(count):
            aid, vid = uuid.uuid4(), uuid.UUID(int=i + 1)
            session.add(
                KnowledgeAsset(
                    id=aid,
                    title="Synthetic reconciliation material",
                    scope="company",
                    zone="material",
                    asset_type="document",
                    owner_user_id=jobs.USER_CONSULTANT,
                    current_version_id=vid,
                    visibility="public",
                    confidentiality_level="L2",
                    ai_access_level="A1",
                )
            )
            session.add(
                KnowledgeAssetVersion(
                    id=vid,
                    asset_id=aid,
                    version_no="V1",
                    version_status="active",
                    created_by=jobs.USER_CONSULTANT,
                    index_status="indexing",
                    weknora_kb_id="synthetic-parse-kb",
                    weknora_doc_id=str(i),
                    weknora_parse_status="processing",
                )
            )
            ids.append(vid)
        await session.commit()
    return ids


async def test_first_200_pending_documents_do_not_starve_ready_tail(job_db, monkeypatch):
    sessions, _ = job_db
    await seed_pending(sessions, 250)
    monkeypatch.setattr(parse_reconcile, "weknora_enabled", lambda: True)
    calls = []

    class Client:
        async def get_knowledge(self, knowledge_id, **kwargs):
            calls.append(knowledge_id)
            return {"parse_status": "processing" if int(knowledge_id) < 200 else "completed"}

    async with sessions() as session:
        first = await parse_reconcile.reconcile_parse_statuses(session, Client())
        second = await parse_reconcile.reconcile_parse_statuses(session, Client())
    assert first["updated"] == 0
    assert second["updated"] == 50, "The fixed-ID prefix starves already completed documents"
    assert set(calls) == {str(i) for i in range(250)}


@pytest.mark.parametrize(
    "exception", [httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError]
)
async def test_transport_failure_does_not_abort_remaining_documents(job_db, monkeypatch, exception):
    sessions, _ = job_db
    ids = await seed_pending(sessions, 2)
    monkeypatch.setattr(parse_reconcile, "weknora_enabled", lambda: True)

    class Client:
        async def get_knowledge(self, knowledge_id, **kwargs):
            if knowledge_id == "0":
                raise exception("synthetic transport failure")
            return {"parse_status": "completed"}

    async with sessions() as session:
        result = await parse_reconcile.reconcile_parse_statuses(session, Client())
        assert result["failed"] == 1 and result["updated"] == 1
        # Leases are released with a fenced bulk UPDATE. Inspect database values,
        # not an ORM instance retained by a handled transport exception traceback.
        tokens = list(
            await session.scalars(
                select(KnowledgeAssetVersion.parse_reconcile_token).where(
                    KnowledgeAssetVersion.id.in_(ids)
                )
            )
        )
        assert tokens == [None, None]


async def test_batch_count_is_bounded_even_for_large_limit(job_db, monkeypatch):
    sessions, _ = job_db
    await seed_pending(sessions, 203)
    monkeypatch.setattr(parse_reconcile, "weknora_enabled", lambda: True)
    calls = []

    class Client:
        async def get_knowledge(self, knowledge_id, **kwargs):
            calls.append(knowledge_id)
            return {"parse_status": "processing"}

    async with sessions() as session:
        await parse_reconcile.reconcile_parse_statuses(session, Client(), limit=10000)
    assert len(calls) <= 200


async def test_batch_deadline_releases_claim_without_false_failure(job_db, monkeypatch):
    sessions, _ = job_db
    ids = await seed_pending(sessions, 2)
    monkeypatch.setattr(parse_reconcile, "weknora_enabled", lambda: True)
    monkeypatch.setattr(parse_reconcile, "_BATCH_TIMEOUT_SECONDS", 0.25, raising=False)
    monkeypatch.setattr(parse_reconcile, "_REQUEST_TIMEOUT_SECONDS", 1)
    calls = []

    class Client:
        async def get_knowledge(self, knowledge_id, **kwargs):
            calls.append(knowledge_id)
            await asyncio.sleep(2)
            return {"parse_status": "completed"}

    async with sessions() as session:
        result = await asyncio.wait_for(
            parse_reconcile.reconcile_parse_statuses(session, Client()), 0.8
        )
        assert result["budget_exhausted"] and result["failed"] == 0
        rows = list(
            await session.scalars(
                select(KnowledgeAssetVersion).where(KnowledgeAssetVersion.id.in_(ids))
            )
        )
        assert len(calls) == 1
        assert all(
            v.parse_reconcile_token is None and v.index_reconcile_failure_count == 0 for v in rows
        )


async def test_new_arrivals_do_not_always_overtake_previously_polled_work(job_db, monkeypatch):
    sessions, _ = job_db
    ids = await seed_pending(sessions, 2)
    monkeypatch.setattr(parse_reconcile, "weknora_enabled", lambda: True)
    calls = []

    class Client:
        async def get_knowledge(self, knowledge_id, **kwargs):
            calls.append(knowledge_id)
            return {"parse_status": "processing"}

    async with sessions() as session:
        await parse_reconcile.reconcile_parse_statuses(session, Client(), limit=1)
        # Represent an arrival after the first document was last polled.
        newer = await session.get(KnowledgeAssetVersion, ids[1])
        newer.created_at = utc_now()
        await session.commit()
        await parse_reconcile.reconcile_parse_statuses(session, Client(), limit=1)
    assert calls == ["0", "0"]


async def test_two_workers_skip_active_and_stale_claims(job_db, monkeypatch):
    sessions, _ = job_db
    await seed_pending(sessions, 5)
    monkeypatch.setattr(parse_reconcile, "weknora_enabled", lambda: True)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    class Client:
        async def get_knowledge(self, knowledge_id, **kwargs):
            calls.append(knowledge_id)
            if knowledge_id == "0":
                entered.set()
                await release.wait()
            return {"parse_status": "completed"}

    async def run():
        async with sessions() as session:
            return await parse_reconcile.reconcile_parse_statuses(session, Client())

    first = asyncio.create_task(run())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        second = await asyncio.wait_for(run(), 5)
        assert second["updated"] == 4
        release.set()
        result = await first
        assert result["updated"] == 1
        assert sorted(calls) == [str(i) for i in range(5)]
    finally:
        release.set()
        await asyncio.gather(first, return_exceptions=True)


@pytest.mark.parametrize("change", ["binding", "terminal", "archived", "reclaimed"])
async def test_changed_state_discards_old_response(job_db, monkeypatch, change):
    sessions, _ = job_db
    (vid,) = await seed_pending(sessions, 1)
    monkeypatch.setattr(parse_reconcile, "weknora_enabled", lambda: True)

    class Client:
        async def get_knowledge(self, knowledge_id, **kwargs):
            async with sessions() as other:
                row = await other.get(KnowledgeAssetVersion, vid)
                if change == "binding":
                    row.weknora_doc_id = "replacement"
                elif change == "terminal":
                    row.weknora_parse_status = "failed"
                elif change == "archived":
                    row.version_status = "archived"
                else:
                    row.parse_reconcile_token = "new-owner"
                    row.parse_reconcile_until = utc_now() + timedelta(minutes=2)
                await other.commit()
            return {"parse_status": "completed"}

    async with sessions() as session:
        result = await parse_reconcile.reconcile_parse_statuses(session, Client())
        assert result["processed"] == result["updated"] == 0
        row = await session.get(KnowledgeAssetVersion, vid)
        assert row.weknora_parse_status == ("failed" if change == "terminal" else "processing")
        assert row.parse_reconcile_token == ("new-owner" if change == "reclaimed" else None)


async def test_cancellation_releases_lease_and_propagates(job_db, monkeypatch):
    sessions, _ = job_db
    (vid,) = await seed_pending(sessions, 1)
    monkeypatch.setattr(parse_reconcile, "weknora_enabled", lambda: True)
    entered = asyncio.Event()

    class Client:
        async def get_knowledge(self, knowledge_id, **kwargs):
            entered.set()
            await asyncio.Event().wait()

    async def run():
        async with sessions() as session:
            await parse_reconcile.reconcile_parse_statuses(session, Client())

    task = asyncio.create_task(run())
    try:
        await asyncio.wait_for(entered.wait(), 5)
    finally:
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with sessions() as check:
        row = await check.get(KnowledgeAssetVersion, vid)
        assert row.parse_reconcile_token is None and row.index_reconcile_failure_count == 0


async def test_request_timeout_does_not_prevent_next_fast_document(job_db, monkeypatch):
    sessions, _ = job_db
    await seed_pending(sessions, 2)
    monkeypatch.setattr(parse_reconcile, "weknora_enabled", lambda: True)
    monkeypatch.setattr(parse_reconcile, "_REQUEST_TIMEOUT_SECONDS", 0.05)

    class Client:
        async def get_knowledge(self, knowledge_id, **kwargs):
            if knowledge_id == "0":
                await asyncio.sleep(2)
            return {"parse_status": "completed"}

    async with sessions() as session:
        result = await parse_reconcile.reconcile_parse_statuses(session, Client())
        assert result["failed"] == result["updated"] == 1
        assert not result["budget_exhausted"]


async def test_expired_lease_is_reclaimed(job_db, monkeypatch):
    sessions, _ = job_db
    (vid,) = await seed_pending(sessions, 1)
    monkeypatch.setattr(parse_reconcile, "weknora_enabled", lambda: True)
    async with sessions() as session:
        row = await session.get(KnowledgeAssetVersion, vid)
        row.parse_reconcile_token = "stopped-worker"
        row.parse_reconcile_until = utc_now() - timedelta(seconds=1)
        await session.commit()

        class Client:
            async def get_knowledge(self, knowledge_id, **kwargs):
                return {"parse_status": "completed"}

        result = await parse_reconcile.reconcile_parse_statuses(session, Client())
        await session.refresh(row)
        assert result["updated"] == 1 and row.parse_reconcile_token is None


@pytest.mark.parametrize("slow", [True, False])
async def test_real_worker_reuses_fast_connections_and_releases_slow_waits(
    job_db, monkeypatch, slow
):
    sessions, _ = job_db
    ids = await seed_pending(sessions, 1 if slow else 20)
    vid = ids[0]
    tag = "kap-parse-" + uuid.uuid4().hex
    async with sessions() as session:
        schema = await session.scalar(text("SELECT current_schema()"))
    entered, release = threading.Event(), threading.Event()
    opened = []

    def engine(url, **options):
        owned = create_async_engine(
            url,
            **options,
            connect_args={"server_settings": {"search_path": schema, "application_name": tag}},
        )
        event.listen(owned.sync_engine, "connect", lambda *_: opened.append(1))
        return owned

    class Client:
        async def get_knowledge(self, knowledge_id, **kwargs):
            if slow:
                entered.set()
                await asyncio.to_thread(release.wait)
            return {"parse_status": "completed"}

    monkeypatch.setattr(runtime, "create_async_engine", engine)
    monkeypatch.setattr(
        runtime,
        "get_settings",
        lambda: SimpleNamespace(
            database_url=sessions.kw["bind"].url,
            db_pool_size=5,
            db_max_overflow=0,
            db_pool_recycle=1800,
        ),
    )
    monkeypatch.setattr(weknora_client, "get_weknora_client", lambda: Client())
    monkeypatch.setattr(parse_reconcile, "weknora_enabled", lambda: True)
    pending = asyncio.create_task(asyncio.to_thread(parse_worker.reconcile_parse.run))
    try:
        if slow:
            assert await asyncio.to_thread(entered.wait, 5)
            for _ in range(30):
                async with sessions() as observer:
                    connections = await observer.scalar(
                        text("SELECT count(*) FROM pg_stat_activity WHERE application_name=:tag"),
                        {"tag": tag},
                    )
                if connections == 0:
                    break
                await asyncio.sleep(0.05)
            assert connections == 0
            async with sessions() as observer:
                row = await observer.get(KnowledgeAssetVersion, vid)
                assert row.parse_reconcile_token and row.parse_reconcile_until > utc_now()
        release.set()
        await pending
        assert len(opened) == (2 if slow else 1)
        async with sessions() as observer:
            row = await observer.get(KnowledgeAssetVersion, vid)
            assert row.index_status == "indexed" and row.parse_reconcile_token is None
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)

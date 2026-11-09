"""Slow synthetic model calls must not reserve the last PostgreSQL connection."""

import asyncio
import json
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_search_api import KA_ALPHA_L4, FakeSearchWeKnora, _insert_alpha_l4

from app.db.base import Base
from app.models.audit import AuditEvent
from app.models.auth_session import UserSession
from app.models.knowledge import KnowledgeAssetChunk, KnowledgeAssetVersion
from app.schemas.search import SearchRequest
from app.seed.dev_seed import (
    KA_COMPANY_L4,
    PROJECT_ALPHA,
    USER_CONSULTANT,
    seed_dev_identities,
    seed_dev_knowledge,
)
from app.services import auth_session, search
from app.services.identity import load_user_with_roles
from app.services.permission import build_caller_context


@pytest_asyncio.fixture
async def single_connection_db():
    url = os.environ.get("KAP_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("KAP_TEST_POSTGRES_URL is required for connection-pool verification")
    assert url.startswith("postgresql+asyncpg://")
    schema = "kap_search_pool_" + uuid.uuid4().hex
    admin = create_async_engine(url)
    engine = create_async_engine(
        url,
        pool_size=1,
        max_overflow=0,
        pool_timeout=1,
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
            await _insert_alpha_l4(session)
            version = await session.scalar(
                select(KnowledgeAssetVersion).where(KnowledgeAssetVersion.asset_id == KA_ALPHA_L4)
            )
            session.add(
                KnowledgeAssetChunk(
                    asset_id=KA_ALPHA_L4,
                    version_id=version.id,
                    chunk_index=0,
                    chunk_type="paragraph",
                    content_text="客户敏感信息及合成方法：先调查，再核验。",
                )
            )
            await session.commit()
        yield sessions
    finally:
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


@pytest.mark.parametrize("stage", ["planning", "recall", "rerank", "scrub", "answer", "original"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_slow_upstream_releases_database_pool(single_connection_db, stage, cancel):
    sessions = single_connection_db
    entered = asyncio.Event()
    release = asyncio.Event()

    async def hold(current):
        if current == stage:
            entered.set()
            await release.wait()

    class Model:
        provider = "test"
        model = "synthetic"

        async def chat_completion(self, messages, **kwargs):
            system = messages[0]["content"]
            if "queries" in system:
                await hold("planning")
                return '{"queries":[]}'
            if '"order"' in system:
                await hold("rerank")
                candidates = json.loads(messages[1]["content"])["candidates"]
                return json.dumps({"order": list(range(len(candidates)))})
            if "脱敏" in system:
                await hold("scrub")
                return "合成脱敏后的交付方法：先调查，再核验。"
            await hold("answer")
            return '{"status":"answered","answer":"合成交付方法。[1]","citation_orders":[1]}'

    class Recall(FakeSearchWeKnora):
        async def search(self, **kwargs):
            await hold("original" if kwargs.get("knowledge_ids") else "recall")
            return await super().search(**kwargs)

    docs = [
        {
            "knowledge_id": f"wk-doc-{KA_ALPHA_L4}",
            "kb_id": f"wk-kb-proj-{PROJECT_ALPHA}",
            "content": "客户敏感信息及合成方法：先调查，再核验。",
        },
        {
            "knowledge_id": f"wk-doc-{KA_COMPANY_L4}",
            "kb_id": "wk-kb-company",
            "content": "合成公司方法。",
        },
    ]
    async with sessions() as session:
        user = await load_user_with_roles(session, user_id=USER_CONSULTANT)
        token = await auth_session.create_session(session, user)
        await session.commit()
        user = await auth_session.resolve_session_user(session, token)
        # The dependency's pending authentication heartbeat must survive the
        # read-session rollbacks, including cancellation during upstream I/O.
        heartbeat = await session.scalar(select(UserSession))
        seen_at = heartbeat.last_seen_at
        caller = build_caller_context(user)
        pending = asyncio.create_task(
            search.run_search(
                session,
                caller,
                SearchRequest(
                    query="合成问答验证",
                    intent="qa",
                    want_original=stage == "original",
                    asset_id=KA_ALPHA_L4 if stage == "original" else None,
                ),
                weknora=Recall(docs),
                llm=Model(),
                trace_id="synthetic-pool-test",
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            # A real competing DB operation must finish while the upstream is
            # deliberately paused, even with a pool of exactly one connection.
            async with sessions() as other:
                assert await asyncio.wait_for(other.scalar(text("SELECT 1")), timeout=0.75) == 1
            assert not pending.done()
            if cancel:
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            else:
                release.set()
                result = await asyncio.wait_for(pending, timeout=5)
                assert len(result.cards) == 2
                assert result.answer_status == "answered"
        finally:
            release.set()
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
    async with sessions() as check:
        assert await check.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.trace_id == "synthetic-pool-test")
        ) == (0 if cancel else 1)
        stored = await check.scalar(select(UserSession))
        assert stored.last_seen_at == seen_at

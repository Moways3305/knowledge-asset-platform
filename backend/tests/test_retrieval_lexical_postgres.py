"""Real PostgreSQL GIN/tokenization/migration regression; no SQLite substitution."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.sql import visitors
from sqlalchemy.sql.elements import BinaryExpression

from app.db.base import Base
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetFileObject
from app.schemas.permission import AccessChannel, CallerContext
from app.seed.dev_seed import (
    KA_PROJECT_ALPHA,
    PROJECT_ALPHA,
    USER_CONSULTANT,
    seed_dev_identities,
    seed_dev_knowledge,
)
from app.services import retrieval_lexical
from app.services.chunking import rebuild_version_chunks
from app.services.permission_rules import load_access_policy
from app.services.retrieval_lexical import (
    _boundary_matches,
    literal_body_statement,
    recall_literal_body,
)
from app.services.storage import LocalFileStorage


async def test_postgres_identifier_index_backfills_and_tracks_updates(tmp_path, monkeypatch):
    url = os.environ.get("KAP_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("KAP_TEST_POSTGRES_URL is required for real PostgreSQL lexical indexing")
    assert url.startswith("postgresql+asyncpg://")
    storage = LocalFileStorage(tmp_path / "canonical")
    monkeypatch.setattr(retrieval_lexical, "get_storage", lambda: storage)
    schema = "kap_lexical_test_" + uuid.uuid4().hex
    admin = create_async_engine(url)
    engine = create_async_engine(
        url,
        connect_args={"server_settings": {"search_path": schema, "statement_timeout": "10000"}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    caller = CallerContext(
        user_id=USER_CONSULTANT,
        is_active=True,
        active_company_roles={"consultant"},
        active_project_ids={PROJECT_ALPHA},
    )
    kb_ids = [f"wk-kb-proj-{PROJECT_ALPHA}"]
    path = Path(__file__).parents[1] / "alembic/versions/0081_chunk_identifier_search.py"
    spec = importlib.util.spec_from_file_location("literal_search_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def migrate(connection, action):
        with Operations.context(MigrationContext.configure(connection)):
            getattr(migration, action)()

    try:
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.run_sync(lambda conn: migrate(conn, "downgrade"))
        async with sessions() as session:
            await seed_dev_identities(session)
            await seed_dev_knowledge(session)
            asset = await session.get(KnowledgeAsset, KA_PROJECT_ALPHA)
            version_id = asset.current_version_id
            source_text = (
                "编号BONUS-NEW-1807已生效。混合编号红队-BONUS_1808可用。\n"
                + "甲" * 507
                + "BONUS-EDGE-1809"
                + "乙" * 600
                + "\n"
                + "丙" * 508
                + "CODE1234"
                + "丁" * 600
                + "\n"
                + "甲" * 508
                + "LINE\n-FAKE-1810"
                + "乙" * 600
                + "\n "
                + "戊" * 506
                + "TRIMMED-EDGE-1811"
                + "己" * 600
            )
            source_bytes = source_text.encode("utf-8")
            source = KnowledgeAssetFileObject(
                asset_id=asset.id,
                version_id=version_id,
                file_variant="canonical_markdown",
                file_name="synthetic.canonical.md",
                file_mime_type="text/markdown",
                # Match existing production canonical objects: size is optional.
                file_size=None,
                file_hash=hashlib.sha256(source_bytes).hexdigest(),
                storage_ref=storage.save(source_bytes, original_name="synthetic.canonical.md"),
                confidentiality_level=asset.confidentiality_level,
            )
            session.add(source)
            await rebuild_version_chunks(
                session,
                asset_id=asset.id,
                version_id=version_id,
                governance_text=source_text,
            )
            await session.commit()
        # Build the actual migration over existing content, not only new rows.
        async with engine.begin() as connection:
            await connection.run_sync(lambda conn: migrate(conn, "upgrade"))
        async with sessions() as session:
            policy = await load_access_policy(session)
            for query in (
                "BONUS-NEW-1807",
                "bonus-new-1807",
                "红队-BONUS_1808",
                "BONUS-EDGE-1809",
                "code1234",
                "TRIMMED-EDGE-1811",
            ):
                found = await recall_literal_body(
                    session,
                    caller,
                    query=query,
                    kb_ids=kb_ids,
                    knowledge_ids=None,
                    channel=AccessChannel.human,
                    policy=policy,
                )
                assert [item[0].id for item in found] == [KA_PROJECT_ALPHA]
            assert (
                await recall_literal_body(
                    session,
                    caller,
                    query="BONUS-NEW-180",
                    kb_ids=kb_ids,
                    knowledge_ids=None,
                    channel=AccessChannel.human,
                    policy=policy,
                )
                == []
            )
            # Real line boundaries are not hard cuts, even when the stripped
            # chunks accidentally form a complete identifier.
            assert (
                await recall_literal_body(
                    session,
                    caller,
                    query="LINE-FAKE-1810",
                    kb_ids=kb_ids,
                    knowledge_ids=None,
                    channel=AccessChannel.human,
                    policy=policy,
                )
                == []
            )
            await session.execute(text("SET LOCAL enable_seqscan = off"))
            statement = literal_body_statement("BONUS-NEW-1807", kb_ids, None, postgresql=True)
            sql = str(
                statement.compile(
                    dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
                )
            )
            plan = await session.scalar(text("EXPLAIN (FORMAT JSON) " + sql))
            assert "ix_knowledge_chunks_identifier_vector" in json.dumps(plan)
            for anchor_is_left, identifier in (
                (True, "CODE1234"),
                (False, "BONUS-EDGE-1809"),
            ):
                boundary = _boundary_matches(
                    identifier, postgresql=True, anchor_is_left=anchor_is_left
                )
                boundary_rows = (await session.execute(boundary)).all()
                assert {
                    (row.asset_id, row.version_id, row.single_chunk) for row in boundary_rows
                } == {(KA_PROJECT_ALPHA, version_id, 0)}
                # A tiny JOIN may correctly prefer the asset/version B-tree
                # over GIN even with seqscan disabled. Prove the actual branch's
                # anchor condition is GIN-usable without dictating join order.
                # Extract its expression/alias rather than recreating a weaker
                # predicate in this test; removing @@ from production must fail.
                anchor_predicates = [
                    node
                    for node in visitors.iterate(boundary.whereclause)
                    if isinstance(node, BinaryExpression)
                    and getattr(node.operator, "opstring", None) == "@@"
                ]
                assert len(anchor_predicates) == 1
                anchor = select(
                    boundary.selected_columns.asset_id,
                    boundary.selected_columns.version_id,
                ).where(anchor_predicates[0])
                anchor_sql = str(
                    anchor.compile(
                        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
                    )
                )
                anchor_plan = await session.scalar(text("EXPLAIN (FORMAT JSON) " + anchor_sql))
                assert "ix_knowledge_chunks_identifier_vector" in json.dumps(anchor_plan)
            await rebuild_version_chunks(
                session,
                asset_id=KA_PROJECT_ALPHA,
                version_id=version_id,
                governance_text="新编号AUTO_UPDATE_1809生效。",
            )
            await session.commit()
            found = await recall_literal_body(
                session,
                caller,
                query="AUTO_UPDATE_1809",
                kb_ids=kb_ids,
                knowledge_ids=None,
                channel=AccessChannel.human,
                policy=policy,
            )
            assert [item[0].id for item in found] == [KA_PROJECT_ALPHA]
            assert (
                await recall_literal_body(
                    session,
                    caller,
                    query="BONUS-NEW-1807",
                    kb_ids=kb_ids,
                    knowledge_ids=None,
                    channel=AccessChannel.human,
                    policy=policy,
                )
                == []
            )
        async with engine.begin() as connection:
            await connection.run_sync(lambda conn: migrate(conn, "downgrade"))
            assert (
                await connection.scalar(
                    text("SELECT to_regclass('ix_knowledge_chunks_identifier_vector')")
                )
                is None
            )
            await connection.run_sync(lambda conn: migrate(conn, "upgrade"))
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()

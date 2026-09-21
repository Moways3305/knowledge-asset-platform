"""Real row-lock regression; requires a disposable PostgreSQL database URL.

Set KAP_TEST_POSTGRES_URL=postgresql+asyncpg://... (never production).
Each test creates and drops only its own randomly named schema.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.directory_migration import DirectoryMigrationCandidate
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.schemas.directory_migration import DirectoryMigrationConfirmRequest
from app.schemas.permission import CallerContext
from app.seed.dev_seed import (
    KA_PROJECT_ALPHA_MATERIAL,
    USER_BOSS,
    seed_dev_identities,
    seed_dev_knowledge,
)
from app.services.directory_migration import confirm


async def test_asset_lock_rechecks_current_version_after_concurrent_switch():
    url = os.environ.get("KAP_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("KAP_TEST_POSTGRES_URL is required for real PostgreSQL row locks")
    assert url.startswith("postgresql+asyncpg://")
    schema = "kap_migration_test_" + uuid.uuid4().hex
    admin = create_async_engine(url)
    engine = create_async_engine(
        url, connect_args={"server_settings": {"search_path": schema, "statement_timeout": "10000"}}
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as setup:
            await seed_dev_identities(setup)
            await seed_dev_knowledge(setup)
            asset = await setup.get(KnowledgeAsset, KA_PROJECT_ALPHA_MATERIAL)
            old_id = asset.current_version_id
            old = await setup.get(KnowledgeAssetVersion, old_id)
            old.directory_key = None
            replacement = KnowledgeAssetVersion(
                asset_id=asset.id,
                version_no="lock-test",
                version_status="draft",
                created_by=USER_BOSS,
            )
            setup.add(replacement)
            await setup.flush()
            new_id = replacement.id
            candidate = DirectoryMigrationCandidate(
                asset_id=asset.id,
                version_id=old_id,
                project_id=asset.project_id,
                scope="project",
                suggested_directory_key="project.deliverables",
                candidate_source="legacy_exact_key",
                confidence="clear",
                status="clear_match",
            )
            setup.add(candidate)
            await setup.commit()
            candidate_id = candidate.id
        async with sessions() as publisher, sessions() as migration, sessions() as observer:
            # Prime the identity map: a locking query must refresh this stale asset too.
            stale = await migration.get(KnowledgeAsset, KA_PROJECT_ALPHA_MATERIAL)
            assert stale.current_version_id == old_id
            await migration.commit()
            migration_pid = await migration.scalar(text("SELECT pg_backend_pid()"))
            locked = await publisher.scalar(
                select(KnowledgeAsset)
                .where(KnowledgeAsset.id == KA_PROJECT_ALPHA_MATERIAL)
                .with_for_update()
            )
            locked.current_version_id = new_id
            await publisher.flush()
            caller = CallerContext(
                user_id=USER_BOSS,
                is_active=True,
                active_company_roles={"boss"},
                active_project_ids=set(),
            )
            pending = asyncio.create_task(
                confirm(
                    migration,
                    caller,
                    DirectoryMigrationConfirmRequest(items=[{"candidate_id": candidate_id}]),
                    "pg-lock-regression",
                )
            )
            try:

                async def wait_until_blocked():
                    while not pending.done():
                        if await observer.scalar(
                            text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                            {"pid": migration_pid},
                        ):
                            return
                        await asyncio.sleep(0.02)
                    pytest.fail("migration did not wait for the asset row lock")

                await asyncio.wait_for(wait_until_blocked(), timeout=5)
                await publisher.commit()
                result = await asyncio.wait_for(pending, timeout=5)
                assert result.failed == 1
                assert result.items[0].reason_code == "active_version_changed"
            finally:
                if not pending.done():
                    pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
                await publisher.rollback()
                await migration.rollback()
        async with sessions() as check:
            assert (await check.get(KnowledgeAssetVersion, old_id)).directory_key is None
            assert (await check.get(KnowledgeAssetVersion, new_id)).directory_key is None
    finally:
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()

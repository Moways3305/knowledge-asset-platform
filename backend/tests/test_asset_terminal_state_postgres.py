"""Asset commands must recheck terminal state after a real PostgreSQL lock wait."""

import asyncio
import os
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.knowledge import KnowledgeAsset
from app.schemas.lifecycle import ArchiveConfirmBody
from app.schemas.permission import CallerContext
from app.seed.dev_seed import KA_COMPANY_L2, USER_BOSS, seed_dev_identities, seed_dev_knowledge
from app.services.knowledge_lifecycle import delete_asset
from app.services.lifecycle import archive_confirm
from app.services.weknora_client import NullWeKnoraClient


@pytest.mark.parametrize("command", ["archive", "delete"])
async def test_asset_command_rechecks_deletion_after_waiting(command):
    url = os.environ.get("KAP_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("KAP_TEST_POSTGRES_URL is required for real PostgreSQL row locks")
    assert url.startswith("postgresql+asyncpg://")
    schema = "kap_asset_lock_" + uuid.uuid4().hex
    admin = create_async_engine(url)
    engine = create_async_engine(
        url, connect_args={"server_settings": {"search_path": schema, "statement_timeout": "10000"}}
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    task = None
    try:
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as setup:
            await seed_dev_identities(setup)
            await seed_dev_knowledge(setup)
        caller = CallerContext(
            user_id=USER_BOSS,
            is_active=True,
            active_company_roles={"boss"},
            active_project_ids=set(),
        )
        async with sessions() as first, sessions() as second:
            cached = await second.get(KnowledgeAsset, KA_COMPANY_L2)
            assert cached.asset_status == "active"
            held = await first.scalar(
                select(KnowledgeAsset).where(KnowledgeAsset.id == KA_COMPANY_L2).with_for_update()
            )
            operation = (
                archive_confirm(
                    second, caller, KA_COMPANY_L2, ArchiveConfirmBody(reason="stale"), "lock-test"
                )
                if command == "archive"
                else delete_asset(
                    second,
                    caller,
                    KA_COMPANY_L2,
                    reason="stale",
                    weknora=NullWeKnoraClient(),
                    trace_id="lock-test",
                    weknora_is_enabled=lambda: False,
                )
            )
            task = asyncio.create_task(operation)
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(task), timeout=0.2)
            held.asset_status = "deleted"
            await first.commit()
            with pytest.raises(HTTPException) as error:
                await asyncio.wait_for(task, timeout=5)
            assert error.value.status_code in {404, 409}
            await second.rollback()
        async with sessions() as check:
            final = await check.get(KnowledgeAsset, KA_COMPANY_L2)
            assert final.asset_status == "deleted"
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()

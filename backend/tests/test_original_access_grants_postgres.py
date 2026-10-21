"""Revocation must recheck a grant changed while waiting on its real PostgreSQL row lock."""

import asyncio
import os
import uuid
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.utils import utc_now
from app.models.original_access import AccessGrant
from app.schemas.permission import CallerContext
from app.seed.dev_seed import (
    KA_COMPANY_L2,
    USER_BOSS,
    USER_CONSULTANT,
    seed_dev_identities,
    seed_dev_knowledge,
)
from app.services.original_access import revoke_grant


async def test_revoke_rechecks_state_after_waiting_for_grant_lock():
    url = os.environ.get("KAP_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("KAP_TEST_POSTGRES_URL is required for real PostgreSQL row locks")
    assert url.startswith("postgresql+asyncpg://")
    schema = "kap_grant_lock_test_" + uuid.uuid4().hex
    admin = create_async_engine(url)
    engine = create_async_engine(
        url,
        connect_args={
            "server_settings": {
                "search_path": schema,
                "statement_timeout": "10000",
            }
        },
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
            grant = AccessGrant(
                asset_id=KA_COMPANY_L2,
                grantee_user_id=USER_CONSULTANT,
                granted_by_user_id=USER_BOSS,
                expires_at=utc_now() + timedelta(days=1),
            )
            setup.add(grant)
            await setup.commit()
            grant_id = grant.id
        caller = CallerContext(
            user_id=USER_BOSS,
            is_active=True,
            active_company_roles={"boss"},
            active_project_ids=set(),
        )
        async with sessions() as first, sessions() as second:
            # Preload an active row to exercise populate_existing after the lock is acquired.
            stale = await second.get(AccessGrant, grant_id)
            assert stale is not None and stale.status == "active"
            held = await first.scalar(
                select(AccessGrant).where(AccessGrant.id == grant_id).with_for_update()
            )
            assert held is not None
            task = asyncio.create_task(
                revoke_grant(second, caller, grant_id, "second", "test-lock")
            )
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(task), timeout=0.2)
            held.status = "revoked"
            held.revoked_at = utc_now()
            held.revoke_reason = "first"
            await first.commit()
            with pytest.raises(HTTPException) as error:
                await asyncio.wait_for(task, timeout=5)
            assert error.value.status_code == 409
            await second.rollback()
        async with sessions() as check:
            final = await check.get(AccessGrant, grant_id)
            assert final is not None and final.revoke_reason == "first"
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()

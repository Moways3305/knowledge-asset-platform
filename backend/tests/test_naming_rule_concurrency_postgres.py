"""Draft writes must recheck their baseline after a real PostgreSQL lock wait."""

import asyncio
import os
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.audit import AuditEvent
from app.models.naming import NamingRuleRevision
from app.schemas.naming import NamingDraftUpdateRequest, NamingPublishRequest
from app.schemas.permission import CallerContext
from app.seed.dev_seed import USER_BOSS, seed_dev_identities
from app.services import naming_rules


@pytest.mark.parametrize("first_action", ["save", "publish"])
@pytest.mark.parametrize("waiting_action", ["save", "publish"])
async def test_waiting_writer_rechecks_draft_and_published_baselines(first_action, waiting_action):
    url = os.environ.get("KAP_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("KAP_TEST_POSTGRES_URL is required for real PostgreSQL row locks")
    assert url.startswith("postgresql+asyncpg://")
    schema = "kap_draft_lock_test_" + uuid.uuid4().hex
    admin = create_async_engine(url)
    engine = create_async_engine(
        url,
        connect_args={"server_settings": {"search_path": schema, "statement_timeout": "10000"}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    pending = None
    caller = CallerContext(
        user_id=USER_BOSS, is_active=True, active_company_roles={"boss"}, active_project_ids=set()
    )
    try:
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as setup:
            await seed_dev_identities(setup)
            initial = await naming_rules.get_rule_center(setup, caller)
            # Make the immutable anchor different from the current published row.
            center = await naming_rules.publish_draft(
                setup,
                caller,
                NamingPublishRequest(
                    expected_base_version=initial.published.version,
                    expected_draft_updated_at=initial.draft.updated_at,
                ),
                "setup-publication",
            )

        async def write(session, action, name):
            baseline = {
                "expected_base_version": center.published.version,
                "expected_draft_updated_at": center.draft.updated_at,
            }
            if action == "publish":
                return await naming_rules.publish_draft(
                    session, caller, NamingPublishRequest(**baseline), name
                )
            directories = [row.model_copy(deep=True) for row in center.draft.config.directories]
            directories[0].display_name = name
            return await naming_rules.save_draft(
                session, caller, NamingDraftUpdateRequest(**baseline, directories=directories), name
            )

        async with sessions() as first, sessions() as waiter, sessions() as observer:
            # Keep strong references to stale identity-map objects while the lock waits.
            stale_rows = (await waiter.execute(select(NamingRuleRevision))).scalars().all()
            assert len(stale_rows) == 3
            await waiter.commit()
            waiter_pid = await waiter.scalar(text("SELECT pg_backend_pid()"))
            await first.execute(
                select(NamingRuleRevision)
                .where(NamingRuleRevision.status == "published")
                .order_by(NamingRuleRevision.version.asc())
                .limit(1)
                .with_for_update()
            )
            pending = asyncio.create_task(write(waiter, waiting_action, "waiting-writer"))

            async def wait_until_blocked():
                while not pending.done():
                    if await observer.scalar(
                        text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": waiter_pid}
                    ):
                        return
                    await asyncio.sleep(0.02)
                pytest.fail("writer did not wait for the stable policy lock")

            await asyncio.wait_for(wait_until_blocked(), timeout=5)
            result = await write(first, first_action, "first-writer")
            with pytest.raises(HTTPException) as error:
                await asyncio.wait_for(pending, timeout=5)
            assert error.value.status_code == 409
            assert error.value.detail["denied_reason"] == (
                "naming_rule_draft_conflict"
                if first_action == "save"
                else "naming_rule_publish_conflict"
            )
            await waiter.rollback()

        async with sessions() as check:
            current = await naming_rules.get_rule_center(check, caller)
            if first_action == "save":
                assert current.draft == result
                assert current.published == center.published
            else:
                assert current == result
            assert await check.scalar(select(func.count()).select_from(AuditEvent)) == 2
            assert (
                await check.scalar(
                    select(func.count())
                    .select_from(NamingRuleRevision)
                    .where(NamingRuleRevision.status == "draft")
                )
                == 1
            )
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()

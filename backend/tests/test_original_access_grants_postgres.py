"""Revocation must recheck a grant changed while waiting on its real PostgreSQL row lock."""

import asyncio
import os
import uuid
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.utils import utc_now
from app.models.audit import AuditEvent
from app.models.knowledge import KnowledgeAsset
from app.models.original_access import AccessGrant, OriginalAccessRequest
from app.models.outbox import DomainEventOutbox
from app.schemas.permission import CallerContext
from app.seed.dev_seed import (
    KA_COMPANY_L2,
    USER_BOSS,
    USER_CONSULTANT,
    seed_dev_identities,
    seed_dev_knowledge,
)
from app.services import knowledge_lifecycle, original_access
from app.services.original_access import revoke_grant
from app.services.permission_rules import load_access_policy
from app.services.weknora_client import NullWeKnoraClient


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


@pytest.mark.parametrize(
    "first_action,waiting_action",
    [("delete", "approve"), ("approve", "delete"), ("delete", "auto"), ("auto", "delete")],
)
async def test_asset_deletion_and_approval_share_lock_order(first_action, waiting_action):
    url = os.environ.get("KAP_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("KAP_TEST_POSTGRES_URL is required for approval/deletion lock tests")
    assert url.startswith("postgresql+asyncpg://")
    schema = "kap_delete_approval_test_" + uuid.uuid4().hex
    admin = create_async_engine(url)
    engine = create_async_engine(
        url,
        connect_args={"server_settings": {"search_path": schema, "statement_timeout": "10000"}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    caller = CallerContext(
        user_id=USER_BOSS, is_active=True, active_company_roles={"boss"}, active_project_ids=set()
    )
    task = None
    try:
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as setup:
            await seed_dev_identities(setup)
            await seed_dev_knowledge(setup)
            request = OriginalAccessRequest(
                asset_id=KA_COMPANY_L2,
                requester_user_id=USER_CONSULTANT,
                status="pending",
                created_at=utc_now() - timedelta(hours=2),
            )
            setup.add(request)
            await setup.commit()
            request_id = request.id

        async def act(session, action):
            if action == "delete":
                return await knowledge_lifecycle.delete_asset(
                    session,
                    caller,
                    KA_COMPANY_L2,
                    reason="synthetic deletion",
                    weknora=NullWeKnoraClient(),
                    trace_id="delete-approval-test",
                    weknora_is_enabled=lambda: False,
                )
            if action == "auto":
                return await original_access._auto_approve_one(
                    session,
                    request_id,
                    now=utc_now(),
                    days=7,
                    timeout_hours=1,
                    policy=await load_access_policy(session),
                    trace_id="delete-approval-test",
                )
            return await original_access.approve_request(
                session, caller, request_id, "synthetic approval", "delete-approval-test"
            )

        async with sessions() as first, sessions() as waiter, sessions() as observer:
            stale_request = await waiter.get(OriginalAccessRequest, request_id)
            stale_asset = await waiter.get(KnowledgeAsset, KA_COMPANY_L2)
            assert stale_request.status == "pending" and stale_asset.asset_status == "active"
            await waiter.commit()
            waiter_pid = await waiter.scalar(text("SELECT pg_backend_pid()"))
            await first.scalar(
                select(KnowledgeAsset).where(KnowledgeAsset.id == KA_COMPANY_L2).with_for_update()
            )
            task = asyncio.create_task(act(waiter, waiting_action))

            async def wait_until_blocked():
                while not task.done():
                    if await observer.scalar(
                        text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": waiter_pid}
                    ):
                        return
                    await asyncio.sleep(0.02)
                pytest.fail("second command did not wait for the shared asset lock")

            await asyncio.wait_for(wait_until_blocked(), timeout=5)
            await act(first, first_action)
            if first_action == "delete" and waiting_action == "approve":
                with pytest.raises(HTTPException) as error:
                    await asyncio.wait_for(task, timeout=5)
                assert error.value.status_code == 409
                assert error.value.detail["denied_reason"] == "request_already_finalized"
            elif first_action == "delete":
                assert await asyncio.wait_for(task, timeout=5) == "skipped_invalid"
            else:
                await asyncio.wait_for(task, timeout=5)
            await waiter.rollback()

        async with sessions() as check:
            asset = await check.get(KnowledgeAsset, KA_COMPANY_L2)
            request = await check.get(OriginalAccessRequest, request_id)
            assert asset.asset_status == "deleted"
            assert request.status == ("cancelled" if first_action == "delete" else "approved")
            grants = list((await check.scalars(select(AccessGrant))).all())
            assert len(grants) == (0 if first_action == "delete" else 1)
            assert all(
                grant.status == "revoked" and grant.revoke_reason == "asset_deleted"
                for grant in grants
            )
            approved_events = list(
                (
                    await check.scalars(
                        select(DomainEventOutbox).where(
                            DomainEventOutbox.event_type == "OriginalAccessDecided"
                        )
                    )
                ).all()
            )
            assert len(approved_events) == (0 if first_action == "delete" else 1)
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()


@pytest.mark.parametrize(
    "first_action,waiting_action",
    [
        ("reject", "approve"),
        ("approve", "reject"),
        ("reject", "auto"),
        ("auto", "reject"),
        ("approve", "approve"),
        ("auto", "auto"),
    ],
)
async def test_request_decisions_recheck_pending_after_real_asset_lock_wait(
    first_action, waiting_action
):
    url = os.environ.get("KAP_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("KAP_TEST_POSTGRES_URL is required for real PostgreSQL request locks")
    assert url.startswith("postgresql+asyncpg://")
    schema = "kap_request_lock_test_" + uuid.uuid4().hex
    admin = create_async_engine(url)
    engine = create_async_engine(
        url,
        connect_args={"server_settings": {"search_path": schema, "statement_timeout": "10000"}},
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    caller = CallerContext(
        user_id=USER_BOSS, is_active=True, active_company_roles={"boss"}, active_project_ids=set()
    )
    task = None
    try:
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as setup:
            await seed_dev_identities(setup)
            await seed_dev_knowledge(setup)
            request = OriginalAccessRequest(
                asset_id=KA_COMPANY_L2,
                requester_user_id=USER_CONSULTANT,
                status="pending",
                created_at=utc_now() - timedelta(hours=2),
            )
            setup.add(request)
            await setup.commit()
            request_id = request.id

        async def decide(session, action):
            if action == "auto":
                return await original_access._auto_approve_one(
                    session,
                    request_id,
                    now=utc_now(),
                    days=7,
                    timeout_hours=1,
                    policy=await load_access_policy(session),
                    trace_id="request-lock-test",
                )
            operation = (
                original_access.approve_request
                if action == "approve"
                else original_access.reject_request
            )
            return await operation(session, caller, request_id, action, "request-lock-test")

        async with sessions() as first, sessions() as waiter, sessions() as observer:
            # Keep a strong reference to the stale pending identity-map row.
            stale = await waiter.get(OriginalAccessRequest, request_id)
            assert stale.status == "pending"
            await waiter.commit()
            waiter_pid = await waiter.scalar(text("SELECT pg_backend_pid()"))
            await first.scalar(
                select(KnowledgeAsset).where(KnowledgeAsset.id == KA_COMPANY_L2).with_for_update()
            )
            held = await first.scalar(
                select(OriginalAccessRequest)
                .where(OriginalAccessRequest.id == request_id)
                .with_for_update()
            )
            assert held.status == "pending"
            task = asyncio.create_task(decide(waiter, waiting_action))

            async def wait_until_blocked():
                while not task.done():
                    if await observer.scalar(
                        text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": waiter_pid}
                    ):
                        return
                    await asyncio.sleep(0.02)
                pytest.fail("second decision did not wait for the asset/request lock order")

            await asyncio.wait_for(wait_until_blocked(), timeout=5)
            await decide(first, first_action)
            if waiting_action == "auto":
                assert await asyncio.wait_for(task, timeout=5) == "skipped_invalid"
            else:
                with pytest.raises(HTTPException) as error:
                    await asyncio.wait_for(task, timeout=5)
                assert error.value.status_code == 409
                assert error.value.detail["denied_reason"] == "request_already_finalized"
            await waiter.rollback()

        async with sessions() as check:
            final = await check.get(OriginalAccessRequest, request_id)
            expected = "rejected" if first_action == "reject" else "approved"
            assert final.status == expected
            grants = list((await check.scalars(select(AccessGrant))).all())
            assert len(grants) == (0 if expected == "rejected" else 1)
            if grants:
                assert grants[0].status == "active" and grants[0].source_request_id == request_id
            assert await check.scalar(select(func.count()).select_from(AuditEvent)) == 1
            events = list(
                (
                    await check.scalars(
                        select(DomainEventOutbox).where(
                            DomainEventOutbox.event_type == "OriginalAccessDecided"
                        )
                    )
                ).all()
            )
            assert len(events) == 1 and events[0].payload["decision"] == expected
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await admin.dispose()

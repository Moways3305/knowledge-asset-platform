"""Independent PostgreSQL connections: no network-time transaction, fenced retries."""

import asyncio
import uuid
from datetime import timedelta

import pytest
import test_job_execution_postgres as jobs
import test_notification_delivery as helpers
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.utils import utc_now
from app.models.audit import AuditEvent
from app.models.identity import User
from app.seed.dev_seed import USER_CONSULTANT

job_db = jobs.job_db
kind = helpers.kind


async def test_one_connection_remains_available_during_send(job_db, kind):
    sessions, _ = job_db
    async with sessions() as setup:
        ids = await helpers.seed(setup, kind)
        schema = await setup.scalar(text("select current_schema()"))
    engine = create_async_engine(
        sessions.kw["bind"].url,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.2,
        connect_args={"server_settings": {"search_path": schema}},
    )
    single = async_sessionmaker(engine, expire_on_commit=False)
    checked = []

    class Inspect:
        async def send(self, **kwargs):
            assert engine.pool.checkedout() == 0
            async with single() as probe:
                assert await probe.scalar(text("select 1")) == 1
                # Releasing the connection must release the row lock too.
                await probe.scalar(
                    select(helpers.model(kind))
                    .where(helpers.model(kind).id == ids[0])
                    .with_for_update(nowait=True)
                )
                checked.append(True)

    try:
        async with single() as session:
            result = await helpers.dispatch(session, kind, Inspect())
        assert result["sent"] == 1 and checked == [True]
    finally:
        await engine.dispose()


async def test_overlapping_dispatchers_cannot_send_same_row(job_db, kind):
    sessions, _ = job_db
    async with sessions() as setup:
        (row_id,) = await helpers.seed(setup, kind)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    class Blocked:
        async def send(self, **kwargs):
            calls.append(1)
            entered.set()
            await release.wait()

    async def run(sender):
        async with sessions() as session:
            return await helpers.dispatch(session, kind, sender)

    first = asyncio.create_task(run(Blocked()))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        duplicates = await asyncio.wait_for(asyncio.gather(*(run(Blocked()) for _ in range(6))), 3)
        assert all(value["processed"] == 0 for value in duplicates)
        assert len(calls) == 1
    finally:
        release.set()
        await first
    async with sessions() as check:
        row = await check.get(helpers.model(kind), row_id)
        assert helpers.attempts(row) == 1 and helpers.status(row) == "sent"
        audits = list(await check.scalars(select(AuditEvent).where(AuditEvent.target_id == row_id)))
        assert len(audits) == 1


async def test_cancelled_dispatch_recovers_only_after_lease_expiry(job_db, kind):
    sessions, _ = job_db
    async with sessions() as setup:
        (row_id,) = await helpers.seed(setup, kind)
    entered = asyncio.Event()

    class Lost:
        async def send(self, **kwargs):
            entered.set()
            await asyncio.Event().wait()

    async def run():
        async with sessions() as session:
            await helpers.dispatch(session, kind, Lost())

    task = asyncio.create_task(run())
    await asyncio.wait_for(entered.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    sender = helpers.Sender()
    async with sessions() as session:
        assert (await helpers.dispatch(session, kind, sender))["processed"] == 0
        row = await session.get(helpers.model(kind), row_id)
        assert row.delivery_token and helpers.attempts(row) == 1
        row.delivery_until = utc_now() - timedelta(seconds=1)
        await session.commit()
        assert (await helpers.dispatch(session, kind, sender))["sent"] == 1
        await session.refresh(row)
        assert helpers.attempts(row) == 2 and row.delivery_token is None
        assert (await helpers.dispatch(session, kind, sender))["processed"] == 0
    assert len(sender.calls) == 1


async def test_reclaimed_owner_cannot_be_overwritten_by_late_result(job_db, kind):
    sessions, _ = job_db
    async with sessions() as setup:
        (row_id,) = await helpers.seed(setup, kind)
    new_token = str(uuid.uuid4())

    class Late:
        async def send(self, **kwargs):
            async with sessions() as competing:
                row = await competing.get(helpers.model(kind), row_id)
                row.delivery_token = new_token
                await competing.commit()

    async with sessions() as session:
        result = await helpers.dispatch(session, kind, Late(), limit=1)
        assert result["sent"] == result["failed"] == 0
        row = await session.get(helpers.model(kind), row_id)
        assert row.delivery_token == new_token and helpers.status(row) == "pending"
        assert not list(
            await session.scalars(select(AuditEvent).where(AuditEvent.target_id == row_id))
        )


async def test_next_recipient_is_reloaded_after_network_wait(job_db, kind):
    sessions, _ = job_db
    async with sessions() as setup:
        ids = await helpers.seed(setup, kind, 2)
    calls = []

    class ChangeDuringSend:
        async def send(self, **kwargs):
            calls.append(1)
            async with sessions() as change:
                user = await change.get(User, USER_CONSULTANT)
                user.status = "inactive"
                await change.commit()

    async with sessions() as session:
        result = await helpers.dispatch(session, kind, ChangeDuringSend())
        assert result["sent"] == result["failed"] == 1 and len(calls) == 1
        rows = list(
            await session.scalars(
                select(helpers.model(kind)).where(helpers.model(kind).id.in_(ids))
            )
        )
        assert sorted(helpers.status(row) for row in rows) == ["failed", "sent"]

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


async def test_worker_continues_both_backlogs_after_releasing_connections(job_db, monkeypatch):
    from app.core.config import get_settings
    from app.services import notification_delivery as delivery
    from app.services import wecom_notification
    from app.worker.tasks import notifications as worker

    sessions, _ = job_db
    ids = {}
    async with sessions() as setup:
        for channel in ("ops", "business"):
            ids[channel] = await helpers.seed(setup, channel, 5)
    sender = helpers.Sender()
    monkeypatch.setattr(delivery, "MAX_BATCH", 2)
    monkeypatch.setattr(wecom_notification, "get_wecom_notification_sender", lambda: sender)
    settings = get_settings().model_copy(update={"celery_task_always_eager": False})
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    wakeups = []

    def publish(**kwargs):
        assert sessions.kw["bind"].pool.checkedout() == 0
        wakeups.append(kwargs)

    monkeypatch.setattr(worker.dispatch_pending, "apply_async", publish)
    await worker._run(sessions, "synthetic-trace")
    assert len(sender.calls) == 4
    assert len(wakeups) == 1
    for _ in range(3):
        if not wakeups:
            break
        message = wakeups.pop(0)
        await worker._run(sessions, **message["kwargs"])
    assert not wakeups and len(sender.calls) == 10
    async with sessions() as check:
        for channel, keys in ids.items():
            rows = list(
                await check.scalars(
                    select(helpers.model(channel)).where(helpers.model(channel).id.in_(keys))
                )
            )
            assert all(helpers.status(r) == "sent" and helpers.attempts(r) == 1 for r in rows)
            audits = list(
                await check.scalars(select(AuditEvent).where(AuditEvent.target_id.in_(keys)))
            )
            assert len(audits) == len(keys)


@pytest.mark.parametrize("sender_kind", ["disabled", "retry"])
async def test_worker_does_not_spin_when_disabled_or_waiting_for_retry(
    job_db, monkeypatch, sender_kind
):
    from app.core.config import get_settings
    from app.services import wecom_notification
    from app.services.wecom_client import WeComError
    from app.worker.tasks import notifications as worker

    sessions, _ = job_db
    settings = get_settings().model_copy(update={"celery_task_always_eager": False})
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    async with sessions() as setup:
        for channel in ("ops", "business"):
            await helpers.seed(setup, channel)
    sender = (
        wecom_notification.NullWeComNotificationSender()
        if sender_kind == "disabled"
        else helpers.Sender(WeComError("wecom_network_error", "synthetic"))
    )
    monkeypatch.setattr(wecom_notification, "get_wecom_notification_sender", lambda: sender)
    wakeups = []
    monkeypatch.setattr(
        worker.dispatch_pending, "apply_async", lambda **kwargs: wakeups.append(kwargs)
    )
    await worker._run(sessions, None)
    assert not wakeups
    await worker._run(sessions, None)
    assert not wakeups
    if sender_kind == "retry":
        assert len(sender.calls) == 2


@pytest.mark.parametrize(
    "condition", ["ready", "backoff", "leased", "exhausted", "abandoned", "locked"]
)
async def test_continuation_only_sees_immediately_claimable_rows(job_db, kind, condition):
    from app.services import notification_delivery as delivery

    sessions, _ = job_db
    async with sessions() as setup:
        (key,) = await helpers.seed(setup, kind)
        row = await setup.get(helpers.model(kind), key)
        if condition == "backoff":
            row.delivery_available_at = utc_now() + timedelta(seconds=120)
        elif condition == "leased":
            row.delivery_until = utc_now() + timedelta(seconds=120)
            row.delivery_token = str(uuid.uuid4())
        elif condition in {"exhausted", "abandoned"}:
            setattr(row, "delivery_attempts" if kind == "business" else "send_attempts", 3)
            if condition == "abandoned":
                row.delivery_until = utc_now() - timedelta(seconds=1)
                row.delivery_token = str(uuid.uuid4())
        await setup.commit()
    async with sessions() as locked, sessions() as check:
        if condition == "locked":
            await locked.scalar(
                select(helpers.model(kind)).where(helpers.model(kind).id == key).with_for_update()
            )
        assert await asyncio.wait_for(delivery.has_ready(check), 1) is (
            condition in {"ready", "abandoned"}
        )
        assert not check.in_transaction()


async def test_time_budget_continues_and_broker_failure_keeps_committed_results(
    job_db, monkeypatch
):
    from types import SimpleNamespace

    from app.core.config import get_settings
    from app.services import notification_delivery as delivery
    from app.services import wecom_notification
    from app.worker.tasks import notifications as worker

    sessions, _ = job_db
    async with sessions() as setup:
        keys = await helpers.seed(setup, "ops", 2)
    clock = [0.0]
    calls = []

    class Slow:
        async def send(self, **kwargs):
            calls.append(1)
            clock[0] += delivery.BATCH_SECONDS

    monkeypatch.setattr(delivery, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(wecom_notification, "get_wecom_notification_sender", Slow)
    settings = get_settings().model_copy(update={"celery_task_always_eager": False})
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    failed_wakeups = []

    def unavailable(**kwargs):
        assert sessions.kw["bind"].pool.checkedout() == 0
        failed_wakeups.append(1)
        raise ConnectionError("synthetic broker unavailable")

    monkeypatch.setattr(worker.dispatch_pending, "apply_async", unavailable)
    await worker._run(sessions, None)
    assert len(calls) == len(failed_wakeups) == 1
    async with sessions() as check:
        rows = list(
            await check.scalars(
                select(helpers.model("ops")).where(helpers.model("ops").id.in_(keys))
            )
        )
        assert sorted(helpers.status(r) for r in rows) == ["pending", "sent"]
    # A subsequent periodic tick finds remaining work even if publication failed.
    await worker._run(sessions, None)
    assert len(calls) == 2 and len(failed_wakeups) == 1

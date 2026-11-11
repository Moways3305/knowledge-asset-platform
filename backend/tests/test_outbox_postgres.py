"""Real PostgreSQL ownership, atomic projections and bounded recipient progress."""

import asyncio
from datetime import timedelta

import pytest
import test_job_execution_postgres as jobs
import test_outbox_pages as pages
from sqlalchemy import func, select

from app.db.utils import utc_now
from app.models.lifecycle import NotificationRecord
from app.models.outbox import DomainEventOutbox
from app.schemas.enums import AuditLogType
from app.seed.dev_seed import KA_COMPANY_L2, USER_CONSULTANT
from app.services import audit, domain_events, outbox

job_db = jobs.job_db


async def seed_local(session):
    fact = await audit.record_system_event(
        session,
        log_type=AuditLogType.operation,
        action="lifecycle_archive_warning",
        trace_id="synthetic-outbox",
        target_type="knowledge_asset",
        target_id=KA_COMPANY_L2,
        extra={"inactive_days": 100},
    )
    await session.flush()
    event = await domain_events.publish(
        session,
        domain_events.DomainEvent(
            event_type=domain_events.LOCAL_NOTIFICATION_REQUESTED,
            aggregate_type="knowledge_asset",
            aggregate_id=KA_COMPANY_L2,
            payload=domain_events.safe_payload(
                notice_type="lifecycle_archive_warning",
                recipient_id=USER_CONSULTANT,
                asset_id=KA_COMPANY_L2,
                audit_event_id=fact.id,
            ),
            idempotency_key=f"synthetic-local:{fact.id}",
        ),
    )
    await session.commit()
    return event.id, fact.id


@pytest.mark.parametrize("late_failure", [False, True])
async def test_reclaimed_owner_cannot_write_notifications_or_failure(
    job_db, monkeypatch, late_failure
):
    sessions, _ = job_db
    async with sessions() as setup:
        event_id, audit_id = await seed_local(setup)
    claimed, resume = asyncio.Event(), asyncio.Event()
    real_claim, real_dispatch = outbox._claim_one, outbox._dispatch

    async def pause_after_claim(session):
        row = await real_claim(session)
        if row is not None and asyncio.current_task().get_name() == "old-owner":
            claimed.set()
            await resume.wait()
        return row

    async def dispatch(session, row):
        if late_failure and asyncio.current_task().get_name() == "old-owner":
            raise RuntimeError("old-owner-failed")
        return await real_dispatch(session, row)

    monkeypatch.setattr(outbox, "_claim_one", pause_after_claim)
    monkeypatch.setattr(outbox, "_dispatch", dispatch)

    async def run():
        async with sessions() as session:
            return await outbox.process_pending(session, limit=1)

    old = asyncio.create_task(run(), name="old-owner")
    try:
        await asyncio.wait_for(claimed.wait(), 3)
        async with sessions() as expire:
            row = await expire.get(DomainEventOutbox, event_id)
            row.claimed_at = utc_now() - timedelta(seconds=outbox.LEASE_SECONDS + 1)
            await expire.commit()
        assert (await run())["processed"] == 1
    finally:
        resume.set()
        await old
    async with sessions() as check:
        row = await check.get(DomainEventOutbox, event_id)
        assert row.status == "completed"
        count = await check.scalar(
            select(func.count())
            .select_from(NotificationRecord)
            .where(NotificationRecord.audit_event_id == audit_id)
        )
        assert count == 1


async def test_active_projection_cannot_be_reclaimed_even_after_lease_deadline(job_db, monkeypatch):
    sessions, _ = job_db
    async with sessions() as setup:
        event_id, audit_id = await seed_local(setup)
    entered, release = asyncio.Event(), asyncio.Event()
    real = outbox._dispatch

    async def block(session, row):
        page = await real(session, row)
        await session.flush()
        entered.set()
        await release.wait()
        return page

    monkeypatch.setattr(outbox, "_dispatch", block)
    monkeypatch.setattr(outbox, "LEASE_SECONDS", -1)

    async def run():
        async with sessions() as session:
            return await outbox.process_pending(session, limit=1)

    first = asyncio.create_task(run())
    try:
        await asyncio.wait_for(entered.wait(), 3)
        results = await asyncio.wait_for(asyncio.gather(*(run() for _ in range(4))), 3)
        assert all(r == {"processed": 0, "failed": 0} for r in results)
    finally:
        release.set()
        await first
    async with sessions() as check:
        assert (await check.get(DomainEventOutbox, event_id)).status == "completed"
        assert (
            await check.scalar(
                select(func.count())
                .select_from(NotificationRecord)
                .where(NotificationRecord.audit_event_id == audit_id)
            )
            == 1
        )


@pytest.mark.parametrize("prior_page", [False, True])
async def test_cancelled_page_rolls_back_notifications_and_cursor(job_db, monkeypatch, prior_page):
    sessions, _ = job_db
    async with sessions() as setup:
        ids = await pages.audience(setup, 65)
        event_id, target = await pages.pending_event(setup)
        if prior_page:
            await outbox.process_pending(setup, limit=1)
    entered = asyncio.Event()
    real = outbox._dispatch

    async def lost(session, row):
        await real(session, row)
        await session.flush()
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(outbox, "_dispatch", lost)

    async def run():
        async with sessions() as session:
            await outbox.process_pending(session, limit=1)

    task = asyncio.create_task(run())
    await asyncio.wait_for(entered.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sessions.kw["bind"].pool.checkedout() == 0
    async with sessions() as check:
        assert len(await pages.notices(check, target)) == (50 if prior_page else 0)
        row = await check.get(DomainEventOutbox, event_id)
        assert row.recipient_cursor == (ids[49] if prior_page else None)
        assert not await outbox.has_ready(check)
        row = await check.get(DomainEventOutbox, event_id)
        row.claimed_at = utc_now() - timedelta(seconds=outbox.LEASE_SECONDS + 1)
        await check.commit()
        monkeypatch.setattr(outbox, "_dispatch", real)
        await outbox.process_pending(check)
        assert len(await pages.notices(check, target)) == 65
        assert (await check.get(DomainEventOutbox, event_id)).status == "completed"


async def test_failure_writeback_cannot_overwrite_a_reclaimed_success(job_db, monkeypatch):
    sessions, _ = job_db
    async with sessions() as setup:
        event_id, _ = await seed_local(setup)
    entered, release = asyncio.Event(), asyncio.Event()
    real_dispatch, real_failure = outbox._dispatch, outbox._record_failure

    async def fail(session, row):
        if row.attempts == 1:
            raise RuntimeError("private details")
        return await real_dispatch(session, row)

    async def pause(*args):
        entered.set()
        await release.wait()
        return await real_failure(*args)

    monkeypatch.setattr(outbox, "_dispatch", fail)
    monkeypatch.setattr(outbox, "_record_failure", pause)

    async def run():
        async with sessions() as session:
            return await outbox.process_pending(session, limit=1)

    old = asyncio.create_task(run(), name="late-failure")
    try:
        await asyncio.wait_for(entered.wait(), 3)
        async with sessions() as expire:
            row = await expire.get(DomainEventOutbox, event_id)
            row.claimed_at = utc_now() - timedelta(seconds=outbox.LEASE_SECONDS + 1)
            await expire.commit()
        await run()
    finally:
        release.set()
        await old
    async with sessions() as check:
        row = await check.get(DomainEventOutbox, event_id)
        assert row.status == "completed" and row.last_error_code is None


async def test_large_audience_yields_and_batch_releases_connection(job_db, monkeypatch):
    sessions, _ = job_db
    async with sessions() as setup:
        await pages.audience(setup, 65)
        _, target = await pages.pending_event(setup)
        local_id, audit_id = await seed_local(setup)
    real = outbox._dispatch

    async def slow_page(session, row):
        page = await real(session, row)
        await asyncio.sleep(0.05)
        return page

    monkeypatch.setattr(outbox, "BATCH_SECONDS", 0.04)
    monkeypatch.setattr(outbox, "_dispatch", slow_page)
    async with sessions() as session:
        assert (await outbox.process_pending(session))["processed"] == 1
        assert sessions.kw["bind"].pool.checkedout() == 0
        assert len(await pages.notices(session, target)) == 50
        assert (await outbox.process_pending(session))["processed"] == 1
        assert (await session.get(DomainEventOutbox, local_id)).status == "completed"
        assert (
            await session.scalar(
                select(func.count())
                .select_from(NotificationRecord)
                .where(NotificationRecord.audit_event_id == audit_id)
            )
            == 1
        )
        assert len(await pages.notices(session, target)) == 50


async def test_lost_continuation_wakeup_is_recovered_from_committed_cursor(job_db, monkeypatch):
    from types import SimpleNamespace

    from app.core import config
    from app.worker.tasks import outbox as worker

    sessions, _ = job_db
    async with sessions() as setup:
        await pages.audience(setup, 65)
        event_id, target = await pages.pending_event(setup)
    real = outbox.process_pending

    async def one(session):
        return await real(session, limit=1)

    def offline():
        raise RuntimeError("broker unavailable")

    monkeypatch.setattr(outbox, "process_pending", one)
    monkeypatch.setattr(
        config, "get_settings", lambda: SimpleNamespace(celery_task_always_eager=False)
    )
    monkeypatch.setattr(worker.dispatch_pending, "delay", offline)
    await worker._run(sessions)
    async with sessions() as check:
        assert (await check.get(DomainEventOutbox, event_id)).status == "pending"
        assert len(await pages.notices(check, target)) == 50
    await worker._run(sessions)  # Same path as the existing periodic beat.
    async with sessions() as check:
        assert (await check.get(DomainEventOutbox, event_id)).status == "completed"
        assert len(await pages.notices(check, target)) == 65


async def test_short_lock_after_claim_does_not_abandon_owned_event(job_db, monkeypatch):
    sessions, _ = job_db
    async with sessions() as setup:
        event_id, _ = await seed_local(setup)
    claimed, resume = asyncio.Event(), asyncio.Event()
    real = outbox._claim_one

    async def pause(session):
        row = await real(session)
        claimed.set()
        await resume.wait()
        return row

    monkeypatch.setattr(outbox, "_claim_one", pause)

    async def run():
        async with sessions() as session:
            return await outbox.process_pending(session, limit=1)

    task = asyncio.create_task(run())
    try:
        await asyncio.wait_for(claimed.wait(), 3)
        async with sessions() as lock:
            await lock.scalar(
                select(DomainEventOutbox).where(DomainEventOutbox.id == event_id).with_for_update()
            )
            resume.set()
            await asyncio.sleep(0.05)
            await lock.rollback()
        assert (await task)["processed"] == 1
        async with sessions() as check:
            assert (await check.get(DomainEventOutbox, event_id)).status == "completed"
    finally:
        resume.set()
        await task

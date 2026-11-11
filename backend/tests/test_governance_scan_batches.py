"""Bounded cycles preserve governance rules, permissions and durable effects."""

import uuid
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, func, select

from app.db.utils import utc_now
from app.models.audit import AuditEvent
from app.models.governance_scan import GovernanceScanRun
from app.models.knowledge import KnowledgeAsset
from app.models.lifecycle import AssetLifecycleEvent
from app.models.outbox import DomainEventOutbox
from app.seed.dev_seed import USER_CONSULTANT
from app.services import knowledge_review
from app.services.jobs import governance_scan, lifecycle_scan


@pytest.fixture(params=["archive", "review"])
def kind(request, monkeypatch):
    monkeypatch.setattr(governance_scan, "BATCH_SIZE", 2)
    monkeypatch.setattr(governance_scan, "BATCH_SECONDS", 100)
    monkeypatch.setattr(lifecycle_scan, "enqueue_outbox_delivery", AsyncMock())
    monkeypatch.setattr(knowledge_review, "enqueue_outbox_delivery", AsyncMock())
    return request.param


async def seed(session, count=5):
    now = utc_now()
    ids = sorted(uuid.uuid4() for _ in range(count))
    for asset_id in ids:
        session.add(
            KnowledgeAsset(
                id=asset_id,
                title="Synthetic governance batch",
                scope="personal",
                zone="asset",
                asset_type="document",
                owner_user_id=USER_CONSULTANT,
                maintainer_user_id=USER_CONSULTANT,
                visibility="private",
                confidentiality_level="L1",
                ai_access_level="A1",
                asset_status="active",
                created_at=now - timedelta(days=900),
                last_called_at=now - timedelta(days=800),
                review_due_at=now - timedelta(days=1),
                updated_at=now - timedelta(days=10),
                verified_updated_at=now - timedelta(days=10),
            )
        )
    await session.commit()
    return ids


async def scan(session, kind, **kwargs):
    if kind == "archive":
        return (await lifecycle_scan.scan_archive_candidates(session, **kwargs))["scanned"]
    return await knowledge_review.scan_due_reviews(session, **kwargs)


async def facts(session, ids):
    return {
        "events": await session.scalar(
            select(func.count())
            .select_from(AssetLifecycleEvent)
            .where(AssetLifecycleEvent.asset_id.in_(ids))
        ),
        "audits": await session.scalar(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.target_id.in_(ids))
        ),
        "outbox": await session.scalar(
            select(func.count())
            .select_from(DomainEventOutbox)
            .where(DomainEventOutbox.aggregate_id.in_(ids))
        ),
    }


async def drain(session, kind, *, first=False):
    counts = [await scan(session, kind, resume_only=not first)]
    for _ in range(30):
        if not await governance_scan.has_pending(session):
            return counts
        counts.append(await scan(session, kind, resume_only=True))
    raise AssertionError("Daily cycle did not drain")


async def test_bounded_batches_finish_and_repeated_trigger_is_idempotent(db_session, kind):
    ids = await seed(db_session)
    counts = await drain(db_session, kind, first=True)
    assert counts == [2, 2, 1]
    before = await facts(db_session, ids)
    assert before == {
        "events": 5 if kind == "archive" else 0,
        "audits": 5 if kind == "archive" else 0,
        "outbox": 5,
    }
    assert await scan(db_session, kind, resume_only=True) == 0
    assert (await drain(db_session, kind, first=True)) == [2, 2, 1]
    assert await facts(db_session, ids) == before
    for asset in await db_session.scalars(select(KnowledgeAsset).where(KnowledgeAsset.id.in_(ids))):
        assert asset.asset_status == "active"
        assert asset.updated_at == asset.verified_updated_at


async def test_elapsed_budget_leaves_unprocessed_assets_for_next_message(
    db_session, kind, monkeypatch
):
    ids = await seed(db_session, 4)
    monkeypatch.setattr(governance_scan, "BATCH_SIZE", 50)
    monkeypatch.setattr(governance_scan, "BATCH_SECONDS", 0)
    assert await drain(db_session, kind, first=True) == [1, 1, 1, 1]
    assert (await facts(db_session, ids))["outbox"] == 4


async def test_new_assets_and_newly_due_reviews_wait_for_next_daily_cycle(db_session, kind):
    await seed(db_session, 3)
    assert await scan(db_session, kind) == 2
    (new_id,) = await seed(db_session, 1)
    row = await db_session.get(KnowledgeAsset, new_id)
    # A normal new asset is outside the current cycle's creation horizon.
    row.created_at = utc_now()
    await db_session.commit()
    assert await drain(db_session, kind) == [1]
    assert (await facts(db_session, [new_id]))["outbox"] == 0
    await drain(db_session, kind, first=True)
    assert (await facts(db_session, [new_id]))["outbox"] == 1


async def test_failed_batch_rolls_back_effects_and_progress_together(db_session, kind, monkeypatch):
    ids = await seed(db_session)
    assert await scan(db_session, kind) == 2
    target = lifecycle_scan if kind == "archive" else knowledge_review.operation_events
    name = "_emit" if kind == "archive" else "publish_knowledge_trust"
    original = getattr(target, name)
    calls = 0

    async def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic transaction interruption")
        return await original(*args, **kwargs)

    monkeypatch.setattr(target, name, fail_second)
    with pytest.raises(RuntimeError, match="synthetic"):
        await scan(db_session, kind, resume_only=True)
    assert (await facts(db_session, ids))["outbox"] == 2
    monkeypatch.setattr(target, name, original)
    assert await drain(db_session, kind) == [2, 1]
    assert (await facts(db_session, ids))["outbox"] == 5


async def test_review_user_contexts_load_once_per_batch(db_session, monkeypatch):
    await seed(db_session, 5)
    monkeypatch.setattr(knowledge_review, "enqueue_outbox_delivery", AsyncMock())
    selects = []

    def observe(_conn, _cursor, sql, *_):
        if "FROM users" in sql:
            selects.append(sql)

    event.listen(db_session.bind.sync_engine, "before_cursor_execute", observe)
    try:
        assert await knowledge_review.scan_due_reviews(db_session) == 5
    finally:
        event.remove(db_session.bind.sync_engine, "before_cursor_execute", observe)
    assert len(selects) == 1


async def test_resume_does_not_start_a_cycle(db_session, kind):
    await seed(db_session)
    assert await scan(db_session, kind, resume_only=True) == 0
    assert await db_session.get(GovernanceScanRun, kind) is None


async def test_deleted_archived_and_future_due_assets_are_not_notified(db_session, kind):
    ids = await seed(db_session, 4)
    rows = [await db_session.get(KnowledgeAsset, asset_id) for asset_id in ids]
    rows[0].deleted_at = utc_now()
    rows[1].asset_status = "archived"
    if kind == "archive":
        rows[2].last_called_at = utc_now()
    else:
        rows[2].review_due_at = utc_now() + timedelta(days=1)
    await db_session.commit()
    assert await drain(db_session, kind, first=True) == [1]
    assert (await facts(db_session, ids))["outbox"] == 1


async def test_review_batch_preserves_recipient_permissions_and_maintainer_fallback(
    db_session, monkeypatch
):
    from app.seed.dev_seed import (
        KA_COMPANY_L2,
        KA_PERSONAL,
        KA_PROJECT_ALPHA,
        USER_BOSS,
        USER_DIRECTOR,
        USER_PROJECT_MANAGER,
    )

    monkeypatch.setattr(knowledge_review, "enqueue_outbox_delivery", AsyncMock())
    for asset_id in (KA_COMPANY_L2, KA_PERSONAL, KA_PROJECT_ALPHA):
        asset = await db_session.get(KnowledgeAsset, asset_id)
        asset.review_due_at = utc_now() - timedelta(days=1)
        # Assigning a consultant does not grant company/project management.
        asset.maintainer_user_id = USER_CONSULTANT
    await db_session.commit()
    assert await knowledge_review.scan_due_reviews(db_session) == 3
    recipients = {}
    for row in await db_session.scalars(
        select(DomainEventOutbox).where(
            DomainEventOutbox.event_type == "KnowledgeTrustActionRequired"
        )
    ):
        recipients.setdefault(row.aggregate_id, set()).add(uuid.UUID(row.payload["recipient_id"]))
    assert recipients == {
        KA_COMPANY_L2: {USER_BOSS, USER_DIRECTOR},
        KA_PERSONAL: {USER_CONSULTANT},
        KA_PROJECT_ALPHA: {USER_PROJECT_MANAGER},
    }


async def test_worker_yields_queue_and_beat_only_resumes_pending_cycles(
    sessionmaker_fixture, monkeypatch
):
    from app.core.config import get_settings
    from app.worker.celery_app import celery_app
    from app.worker.tasks.lifecycle import _run, archive_scan

    monkeypatch.setattr(governance_scan, "BATCH_SIZE", 2)
    monkeypatch.setattr(governance_scan, "BATCH_SECONDS", 100)
    monkeypatch.setattr(lifecycle_scan, "enqueue_outbox_delivery", AsyncMock())
    monkeypatch.setattr(knowledge_review, "enqueue_outbox_delivery", AsyncMock())
    monkeypatch.setattr(get_settings(), "celery_task_always_eager", False)
    wakeups = []
    monkeypatch.setattr(archive_scan, "apply_async", lambda **kwargs: wakeups.append(kwargs))
    async with sessionmaker_fixture() as session:
        ids = await seed(session)
    await _run(sessionmaker_fixture, "synthetic", resume_only=True)
    assert wakeups == []
    await _run(sessionmaker_fixture, "synthetic")
    assert wakeups == [{"kwargs": {"trace_id": "synthetic", "resume_only": True}}]
    await _run(sessionmaker_fixture, "synthetic", resume_only=True)
    await _run(sessionmaker_fixture, "synthetic", resume_only=True)
    assert len(wakeups) == 2
    async with sessionmaker_fixture() as session:
        assert (await facts(session, ids))["outbox"] == 10
        assert not await governance_scan.has_pending(session)
    entry = celery_app.conf.beat_schedule["lifecycle-resume-scan"]
    assert entry == {
        "task": "lifecycle.archive_scan",
        "schedule": 60.0,
        "kwargs": {"resume_only": True},
    }


async def test_broker_failure_leaves_progress_for_resume_beat(sessionmaker_fixture, monkeypatch):
    from app.core.config import get_settings
    from app.worker.tasks.lifecycle import _run, archive_scan

    monkeypatch.setattr(governance_scan, "BATCH_SIZE", 2)
    monkeypatch.setattr(lifecycle_scan, "enqueue_outbox_delivery", AsyncMock())
    monkeypatch.setattr(knowledge_review, "enqueue_outbox_delivery", AsyncMock())
    monkeypatch.setattr(get_settings(), "celery_task_always_eager", False)

    def unavailable(**kwargs):
        raise OSError("synthetic broker unavailable")

    monkeypatch.setattr(archive_scan, "apply_async", unavailable)
    async with sessionmaker_fixture() as session:
        ids = await seed(session, 3)
    await _run(sessionmaker_fixture, None)
    async with sessionmaker_fixture() as session:
        assert await governance_scan.has_pending(session)
    await _run(sessionmaker_fixture, None, resume_only=True)
    async with sessionmaker_fixture() as session:
        assert not await governance_scan.has_pending(session)
        assert (await facts(session, ids))["outbox"] == 6


async def test_failure_before_first_archive_batch_still_leaves_review_cycle_pending(
    sessionmaker_fixture, monkeypatch
):
    from app.worker.tasks.lifecycle import _run

    monkeypatch.setattr(governance_scan, "BATCH_SIZE", 50)
    monkeypatch.setattr(lifecycle_scan, "enqueue_outbox_delivery", AsyncMock())
    monkeypatch.setattr(knowledge_review, "enqueue_outbox_delivery", AsyncMock())
    original = lifecycle_scan._emit
    monkeypatch.setattr(
        lifecycle_scan, "_emit", AsyncMock(side_effect=RuntimeError("synthetic first-batch crash"))
    )
    async with sessionmaker_fixture() as session:
        ids = await seed(session, 3)
    with pytest.raises(RuntimeError, match="synthetic"):
        await _run(sessionmaker_fixture, None)
    async with sessionmaker_fixture() as session:
        assert set(
            await session.scalars(
                select(GovernanceScanRun.name).where(GovernanceScanRun.completed_at.is_(None))
            )
        ) == {"archive", "review"}
        assert (await facts(session, ids))["outbox"] == 0
    monkeypatch.setattr(lifecycle_scan, "_emit", original)
    await _run(sessionmaker_fixture, None, resume_only=True)
    async with sessionmaker_fixture() as session:
        assert not await governance_scan.has_pending(session)
        assert (await facts(session, ids))["outbox"] == 6

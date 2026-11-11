"""Reuse batching preserves thresholds, recipients, content baselines and recovery."""

import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import event, func, select, update
from test_celery_tasks import _cite_asset

from app.db.utils import utc_now
from app.models.agent import AgentCallCitation
from app.models.audit import AuditEvent
from app.models.governance_scan import GovernanceScanRun
from app.models.knowledge import KnowledgeAsset
from app.models.outbox import DomainEventOutbox
from app.seed.dev_seed import PROJECT_ALPHA, PROJECT_BETA, USER_CONSULTANT
from app.services.jobs import governance_scan, reuse_upgrade


@pytest.fixture(autouse=True)
def batches(monkeypatch):
    monkeypatch.setattr(governance_scan, "BATCH_SIZE", 2)
    monkeypatch.setattr(governance_scan, "BATCH_SECONDS", 100)
    monkeypatch.setattr(reuse_upgrade, "enqueue_outbox_delivery", AsyncMock())


async def seed(session, count=5, *, citations=3, usage_current=False):
    now = utc_now()
    ids = sorted(uuid.uuid4() for _ in range(count))
    for asset_id in ids:
        session.add(
            KnowledgeAsset(
                id=asset_id,
                title="Synthetic reuse",
                scope="project",
                project_id=PROJECT_ALPHA,
                zone="asset",
                asset_type="document",
                owner_user_id=USER_CONSULTANT,
                visibility="project",
                confidentiality_level="L2",
                ai_access_level="A1",
                asset_status="active",
                created_at=now - timedelta(days=10),
                updated_at=now - timedelta(days=5),
                verified_updated_at=now - timedelta(days=5),
                last_called_at=now + timedelta(days=1) if usage_current else None,
            )
        )
    await session.commit()
    for asset_id in ids:
        for _ in range(citations):
            await _cite_asset(session, asset_id=asset_id, project_id=PROJECT_ALPHA)
    return ids


async def facts(session, ids):
    audits = list(
        await session.scalars(
            select(AuditEvent).where(
                AuditEvent.target_id.in_(ids), AuditEvent.action == "knowledge.upgrade_recommended"
            )
        )
    )
    events = await session.scalar(
        select(func.count())
        .select_from(DomainEventOutbox)
        .where(DomainEventOutbox.aggregate_id.in_(ids))
    )
    return len(audits), events


async def drain(session, *, first=False, **kwargs):
    results = []
    for n in range(30):
        results.append(
            await reuse_upgrade.scan_reuse_and_recommend(
                session, resume_only=not first or n > 0, **kwargs
            )
        )
        if not await governance_scan.has_pending(session, ("reuse",)):
            return results
    raise AssertionError("Reuse cycle failed to finish")


async def test_batches_replay_and_business_baselines(db_session):
    ids = await seed(db_session)
    result = await drain(db_session, first=True)
    assert [r["assets"] for r in result] == [2, 2, 1]
    assert sum(r["usage_updated"] for r in result) == 5
    assert sum(r["recommended"] for r in result) == 5
    assert await facts(db_session, ids) == (5, 10)  # Boss + director, once each.
    assert (await reuse_upgrade.scan_reuse_and_recommend(db_session, resume_only=True))[
        "assets"
    ] == 0
    repeated = await drain(db_session, first=True)
    assert sum(r["recommended"] + r["usage_updated"] for r in repeated) == 0
    assert await facts(db_session, ids) == (5, 10)
    for asset in await db_session.scalars(select(KnowledgeAsset).where(KnowledgeAsset.id.in_(ids))):
        assert asset.scope == "project" and asset.zone == "asset" and asset.asset_status == "active"
        assert asset.updated_at == asset.verified_updated_at and asset.last_called_at is not None


async def test_budget_and_frozen_thresholds(db_session, monkeypatch):
    ids = await seed(db_session, 3)
    monkeypatch.setattr(governance_scan, "BATCH_SECONDS", 0)
    first = await reuse_upgrade.scan_reuse_and_recommend(db_session, min_calls=99)
    assert first == {"assets": 1, "recommended": 0, "usage_updated": 1}
    # Resuming with defaults must not change a cycle's recommendation threshold.
    rest = await drain(db_session)
    assert [r["assets"] for r in rest] == [1, 1]
    assert await facts(db_session, ids) == (0, 0)


async def test_scans_only_live_cited_assets_and_preserves_status_rules(db_session):
    ids = await seed(db_session, 6)
    statuses = ["active", "archived", "needs_update", "active", "active", "active"]
    for index, asset_id in enumerate(ids):
        asset = await db_session.get(KnowledgeAsset, asset_id)
        asset.asset_status = statuses[index]
        if index == 3:
            asset.scope = "company"
        if index == 4:
            asset.deleted_at = utc_now()
        if index == 5:
            asset.scope = "personal"
    await db_session.commit()
    result = await drain(db_session, first=True)
    assert sum(r["assets"] for r in result) == 5
    assert sum(r["usage_updated"] for r in result) == 5
    assert await facts(db_session, ids) == (1, 2)
    deleted = await db_session.get(KnowledgeAsset, ids[4])
    assert deleted.last_called_at is None and deleted.reuse_scan_checked_at is None


async def test_distinct_projects_and_citation_count_keep_existing_rules(db_session):
    ids = await seed(db_session, 2, citations=1)
    await _cite_asset(db_session, asset_id=ids[0], project_id=PROJECT_BETA)
    # Multiple chunks in ONE call still count as citation rows, as before.
    citation = await db_session.scalar(
        select(AgentCallCitation).where(AgentCallCitation.cited_asset_id == ids[1])
    )
    db_session.add_all(
        AgentCallCitation(
            call_id=citation.call_id,
            decision_item_id=citation.decision_item_id,
            cited_asset_id=ids[1],
            used_access_layer="original",
            cited_zone="asset",
            citation_order=n,
        )
        for n in (2, 3)
    )
    await db_session.commit()
    await drain(db_session, first=True)
    rows = list(await db_session.scalars(select(AuditEvent).where(AuditEvent.target_id.in_(ids))))
    counts = {(r.extra["reuse_project_count"], r.extra["reuse_call_count"]) for r in rows}
    assert counts == {(2, 2), (1, 3)}


async def test_new_citations_and_assets_wait_for_next_cycle(db_session):
    ids = await seed(db_session, 3, citations=1)
    await reuse_upgrade.scan_reuse_and_recommend(db_session, min_calls=2)
    # This asset is still pending but its new citation belongs to the next cycle.
    await _cite_asset(db_session, asset_id=ids[2], project_id=PROJECT_ALPHA)
    new_ids = await seed(db_session, 1, citations=3)
    await drain(db_session)
    assert await facts(db_session, ids + new_ids) == (0, 0)
    await drain(db_session, first=True, min_calls=2)
    assert await facts(db_session, ids + new_ids) == (2, 4)


async def test_exception_rolls_back_events_usage_and_markers(db_session, monkeypatch):
    ids = await seed(db_session, 3)
    original = reuse_upgrade.operation_events.publish_local_notification

    async def fail(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("synthetic interruption")

    monkeypatch.setattr(reuse_upgrade.operation_events, "publish_local_notification", fail)
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        await reuse_upgrade.scan_reuse_and_recommend(db_session)
    assert await facts(db_session, ids) == (0, 0)
    assert await governance_scan.has_pending(db_session, ("reuse",))
    for asset in await db_session.scalars(select(KnowledgeAsset).where(KnowledgeAsset.id.in_(ids))):
        assert asset.last_called_at is None and asset.reuse_scan_checked_at is None
    monkeypatch.setattr(reuse_upgrade.operation_events, "publish_local_notification", original)
    await drain(db_session)
    assert await facts(db_session, ids) == (3, 6)


async def test_every_aggregation_is_bounded_and_history_loaded_once(db_session):
    await seed(db_session)
    statements = []

    def capture(_conn, _cursor, sql, *_rest):
        statements.append(sql)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = await reuse_upgrade.scan_reuse_and_recommend(db_session)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert result["assets"] == 2
    grouped = [s for s in statements if "GROUP BY agent_call_citations.cited_asset_id" in s]
    assert grouped and all("agent_call_citations.cited_asset_id IN" in s for s in grouped)
    assert len([s for s in statements if "FROM audit_events" in s]) == 1
    assert len([s for s in statements if "FROM user_company_roles" in s]) == 1


async def test_pending_intentions_do_not_cross_job_families(db_session):
    assert not (await reuse_upgrade.scan_reuse_and_recommend(db_session, resume_only=True))[
        "assets"
    ]
    assert await db_session.scalar(select(func.count()).select_from(GovernanceScanRun)) == 0
    await governance_scan.begin_cycle(db_session, "reuse", resume_only=False)
    await db_session.commit()
    assert not await governance_scan.has_pending(db_session)
    assert await governance_scan.has_pending(db_session, ("reuse",))
    await db_session.execute(update(GovernanceScanRun).values(completed_at=utc_now()))
    await governance_scan.start_daily_cycles(db_session)
    assert await governance_scan.has_pending(db_session)
    assert not await governance_scan.has_pending(db_session, ("reuse",))


async def test_worker_yields_and_broker_failure_keeps_progress(db_session, monkeypatch):
    from app.core.config import get_settings
    from app.worker.celery_app import celery_app
    from app.worker.tasks import upgrade

    await seed(db_session, 3)
    monkeypatch.setattr(get_settings(), "celery_task_always_eager", False)
    wake = Mock(side_effect=RuntimeError("synthetic broker unavailable"))
    monkeypatch.setattr(upgrade.upgrade_scan, "apply_async", wake)

    # The fixture owns this session; the wrapper still must close its context.
    class Context:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *_args):
            await db_session.rollback()

    await upgrade._run(Context, "trace")
    wake.assert_called_once_with(kwargs={"trace_id": "trace", "resume_only": True})
    assert await governance_scan.has_pending(db_session, ("reuse",))
    await upgrade._run(Context, "trace", resume_only=True)
    assert not await governance_scan.has_pending(db_session, ("reuse",))
    beat = celery_app.conf.beat_schedule["reuse-resume-scan"]
    assert beat["task"] == "reuse.upgrade_scan" and beat["kwargs"] == {"resume_only": True}

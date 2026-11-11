"""Fair timeout scans preserve pending human work and live authorization rules."""

import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import func, select, update
from test_permission_runtime import COMPANY, TIMEOUT, _set_numeric, _set_toggle

from app.db.utils import utc_now
from app.models.audit import AuditEvent
from app.models.governance_scan import GovernanceScanRun
from app.models.identity import User
from app.models.knowledge import KnowledgeAsset
from app.models.original_access import AccessGrant, OriginalAccessRequest
from app.models.outbox import DomainEventOutbox
from app.models.permission_rule import PermissionRule
from app.seed.dev_seed import USER_BOSS, USER_CONSULTANT
from app.services import original_access
from app.services.jobs import governance_scan
from app.services.jobs import original_access_scan as scan


@pytest.fixture(autouse=True)
def scan_setup(monkeypatch):
    monkeypatch.setattr(scan, "BATCH_SECONDS", 100)
    monkeypatch.setattr(original_access, "enqueue_outbox_delivery", AsyncMock())


async def seed(session, blocked=2, eligible=3):
    await _set_numeric(session, TIMEOUT, value_number=1, enabled=True)
    await _set_toggle(session, COMPANY, value_bool=False)
    now = utc_now()
    requests, assets = [], []
    for i in range(blocked + eligible):
        asset_id = uuid.uuid4()
        session.add(
            KnowledgeAsset(
                id=asset_id,
                title="Synthetic access scan",
                scope="company",
                zone="asset",
                asset_type="document",
                owner_user_id=USER_BOSS,
                visibility="company",
                confidentiality_level="L3" if i < blocked else "L2",
                ai_access_level="A1",
                asset_status="active",
                created_at=now - timedelta(days=10),
                updated_at=now - timedelta(days=5),
                verified_updated_at=now - timedelta(days=5),
            )
        )
        await session.flush()
        req = OriginalAccessRequest(
            id=uuid.uuid4(),
            asset_id=asset_id,
            requester_user_id=USER_CONSULTANT,
            status="pending",
            created_at=now - timedelta(hours=5) + timedelta(seconds=i),
            updated_at=now - timedelta(hours=2),
        )
        session.add(req)
        requests.append(req.id)
        assets.append(asset_id)
    await session.commit()
    return requests, assets


async def counts(session, ids, assets):
    grants = await session.scalar(
        select(func.count()).select_from(AccessGrant).where(AccessGrant.asset_id.in_(assets))
    )
    outbox = await session.scalar(
        select(func.count())
        .select_from(DomainEventOutbox)
        .where(DomainEventOutbox.aggregate_id.in_(ids))
    )
    audits = await session.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.target_id.in_(
                select(AccessGrant.id).where(AccessGrant.asset_id.in_(assets))
            ),
            AuditEvent.action == "access.original_approved",
        )
    )
    return grants, audits, outbox


async def run(session, **kwargs):
    return await original_access.auto_approve_timed_out_original_access_requests(
        session, trace_id="test-fair-access", **kwargs
    )


async def drain(session, *, first=False, **kwargs):
    results = []
    for index in range(200):
        results.append(await run(session, resume_only=not first or index > 0, **kwargs))
        if not await governance_scan.has_pending(session, (scan.NAME,)):
            return results
    raise AssertionError("Timeout sweep did not finish")


async def test_hundred_skipped_requests_cannot_starve_eligible_tail(db_session):
    ids, assets = await seed(db_session, 100, 20)
    before = list(
        (
            await db_session.execute(
                select(
                    OriginalAccessRequest.id,
                    OriginalAccessRequest.updated_at,
                )
                .where(OriginalAccessRequest.id.in_(ids[:100]))
                .order_by(OriginalAccessRequest.id)
            )
        ).all()
    )
    first = await run(db_session)
    assert first["checked"] == 100 and first["skipped_confidential"] == 100
    second = await run(db_session, resume_only=True)
    assert second["checked"] == second["approved"] == 20
    assert not await governance_scan.has_pending(db_session, (scan.NAME,))
    assert await counts(db_session, ids, assets) == (20, 20, 20)
    after = list(
        (
            await db_session.execute(
                select(
                    OriginalAccessRequest.id,
                    OriginalAccessRequest.updated_at,
                )
                .where(OriginalAccessRequest.id.in_(ids[:100]))
                .order_by(OriginalAccessRequest.id)
            )
        ).all()
    )
    assert after == before  # Skipping is not a human decision or a business edit.
    assert all(
        r.status == "pending" and r.review_note is None
        for r in await db_session.scalars(
            select(OriginalAccessRequest).where(OriginalAccessRequest.id.in_(ids[:100]))
        )
    )
    await drain(db_session, first=True)
    assert await counts(db_session, ids, assets) == (20, 20, 20)


async def test_budget_and_resume_do_not_start_another_sweep(db_session, monkeypatch):
    assert (await run(db_session, resume_only=True))["checked"] == 0
    assert await db_session.scalar(select(func.count()).select_from(GovernanceScanRun)) == 0
    ids, assets = await seed(db_session)
    monkeypatch.setattr(scan, "BATCH_SECONDS", 0)
    results = await drain(db_session, first=True)
    assert [r["checked"] for r in results] == [1] * 5
    assert await counts(db_session, ids, assets) == (3, 3, 3)
    assert not await governance_scan.has_pending(db_session)
    assert (await run(db_session, resume_only=True))["checked"] == 0


async def test_rule_disable_stops_resume_and_reenable_uses_new_sweep(db_session):
    ids, assets = await seed(db_session, 0, 3)
    assert (await run(db_session, limit=1))["approved"] == 1
    await _set_numeric(db_session, TIMEOUT, enabled=False)
    disabled = await run(db_session, resume_only=True)
    assert not disabled["enabled"] and disabled["approved"] == 0
    assert not await governance_scan.has_pending(db_session, (scan.NAME,))
    assert await counts(db_session, ids, assets) == (1, 1, 1)
    await _set_numeric(db_session, TIMEOUT, enabled=True)
    assert (await run(db_session, resume_only=True))["checked"] == 0
    await drain(db_session, first=True)
    assert await counts(db_session, ids, assets) == (3, 3, 3)


async def test_longer_timeout_and_inactive_requester_rechecked_between_batches(db_session):
    ids, assets = await seed(db_session, 0, 3)
    assert (await run(db_session, limit=1))["approved"] == 1
    await _set_numeric(db_session, TIMEOUT, value_number=12)
    assert (await run(db_session, resume_only=True))["checked"] == 0
    await _set_numeric(db_session, TIMEOUT, value_number=1)
    await db_session.execute(
        update(User).where(User.id == USER_CONSULTANT).values(status="inactive")
    )
    await db_session.commit()
    result = await run(db_session)
    assert result["skipped_invalid"] == 2 and result["approved"] == 0
    assert await counts(db_session, ids, assets) == (1, 1, 1)


async def test_stale_loaded_rule_and_asset_do_not_authorize(db_session):
    ids, assets = await seed(db_session, 0, 1)
    rule = await db_session.scalar(select(PermissionRule).where(PermissionRule.rule_key == TIMEOUT))
    await db_session.execute(
        update(PermissionRule)
        .where(PermissionRule.id == rule.id)
        .values(enabled=False)
        .execution_options(synchronize_session=False)
    )
    await db_session.commit()
    assert rule.enabled
    assert not (await run(db_session))["enabled"]
    assert await counts(db_session, ids, assets) == (0, 0, 0)


async def test_failed_item_advances_but_keeps_pending_for_next_pass(db_session, monkeypatch):
    ids, assets = await seed(db_session, 0, 3)
    ensure = original_access._ensure_active_grant_for_request

    async def fail(session, **kwargs):
        if kwargs["req"].id == ids[0]:
            raise RuntimeError("synthetic failure")
        return await ensure(session, **kwargs)

    monkeypatch.setattr(original_access, "_ensure_active_grant_for_request", fail)
    result = await run(db_session)
    assert result["errors"] == 1 and result["approved"] == 2
    assert (await db_session.get(OriginalAccessRequest, ids[0])).status == "pending"
    assert await counts(db_session, ids, assets) == (2, 2, 2)
    monkeypatch.setattr(original_access, "_ensure_active_grant_for_request", ensure)
    assert (await run(db_session))["approved"] == 1
    assert await counts(db_session, ids, assets) == (3, 3, 3)


async def test_skipped_item_is_reconsidered_when_asset_becomes_eligible(db_session):
    ids, assets = await seed(db_session, 1, 0)
    assert (await run(db_session))["skipped_confidential"] == 1
    await db_session.execute(
        update(KnowledgeAsset)
        .where(KnowledgeAsset.id == assets[0])
        .values(confidentiality_level="L2")
    )
    await db_session.commit()
    assert (await run(db_session, resume_only=True))["checked"] == 0
    assert (await run(db_session))["approved"] == 1
    assert await counts(db_session, ids, assets) == (1, 1, 1)


async def test_equal_creation_times_use_id_tie_breaker_without_skipping(db_session):
    ids, assets = await seed(db_session, 0, 5)
    await db_session.execute(
        update(OriginalAccessRequest)
        .where(OriginalAccessRequest.id.in_(ids))
        .values(created_at=utc_now() - timedelta(hours=5))
    )
    await db_session.commit()
    results = await drain(db_session, first=True, limit=1)
    assert [r["checked"] for r in results] == [1] * 5
    assert await counts(db_session, ids, assets) == (5, 5, 5)


async def test_fixed_cutoff_leaves_newly_timed_out_requests_for_next_cycle(db_session):
    ids, assets = await seed(db_session, 0, 3)
    now = utc_now()
    await db_session.execute(
        update(OriginalAccessRequest)
        .where(OriginalAccessRequest.id == ids[2])
        .values(created_at=now)
    )
    await db_session.commit()
    assert (await run(db_session, now=now, limit=1))["approved"] == 1
    assert (await run(db_session, now=now + timedelta(hours=3), resume_only=True))["approved"] == 1
    assert await counts(db_session, ids, assets) == (2, 2, 2)
    assert (await run(db_session, now=now + timedelta(hours=3)))["approved"] == 1


async def test_worker_continuation_survives_broker_failure(db_session, monkeypatch):
    from app.core.config import get_settings
    from app.worker.celery_app import celery_app
    from app.worker.tasks import original_access as worker

    await seed(db_session, 0, 3)
    monkeypatch.setattr(scan, "BATCH_SIZE", 2)
    monkeypatch.setattr(get_settings(), "celery_task_always_eager", False)
    wake = Mock(side_effect=RuntimeError("synthetic broker unavailable"))
    monkeypatch.setattr(worker.auto_approve_timed_out, "apply_async", wake)

    class Context:
        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *_args):
            await db_session.rollback()

    await worker._run(Context, "trace")
    wake.assert_called_once_with(kwargs={"trace_id": "trace", "resume_only": True})
    assert await governance_scan.has_pending(db_session, (scan.NAME,))
    await worker._run(Context, "trace", resume_only=True)
    assert not await governance_scan.has_pending(db_session, (scan.NAME,))
    assert celery_app.conf.beat_schedule["original-access-resume"]["kwargs"] == {
        "resume_only": True
    }

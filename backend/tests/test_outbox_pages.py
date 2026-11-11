"""Bounded audiences preserve eligibility, durable progress and notification facts."""

import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.db.utils import utc_now
from app.models.identity import ProjectMember, User, UserCompanyRole
from app.models.lifecycle import AlertRule, NotificationRecord
from app.models.notification import BusinessNotification
from app.models.original_access import OriginalAccessRequest
from app.models.outbox import DomainEventOutbox
from app.models.review import ReviewTask
from app.schemas.enums import AuditLogType
from app.seed.dev_seed import KA_COMPANY_L2, PROJECT_ALPHA, REVIEW_SEED, USER_CONSULTANT
from app.services import alert, audit, domain_events, operation_events, outbox


async def audience(session, count, *, admins=False):
    await session.execute(update(UserCompanyRole).values(status="inactive"))
    ids = [uuid.UUID(int=1000 + i) for i in range(count)]
    session.add_all(
        User(id=u, name="Synthetic", email=f"{u}@example.invalid", status="active") for u in ids
    )
    await session.flush()
    for user_id in ids:
        session.add(UserCompanyRole(user_id=user_id, company_role="boss", status="active"))
        if admins:
            session.add(UserCompanyRole(user_id=user_id, company_role="admin", status="active"))
    await session.commit()
    return ids


async def pending_event(session):
    req = OriginalAccessRequest(
        id=uuid.uuid4(), asset_id=KA_COMPANY_L2, requester_user_id=USER_CONSULTANT, status="pending"
    )
    session.add(req)
    await session.flush()
    event = await domain_events.publish(
        session,
        domain_events.DomainEvent(
            event_type=domain_events.ORIGINAL_ACCESS_REQUESTED,
            aggregate_type="original_access_request",
            aggregate_id=req.id,
            payload={},
            idempotency_key=f"pending:{req.id}",
        ),
    )
    await session.commit()
    return event.id, req.id


async def notices(session, target_id):
    return list(
        await session.scalars(
            select(BusinessNotification).where(BusinessNotification.target_id == target_id)
        )
    )


async def test_large_audience_does_not_exhaust_retry_budget(db_session):
    session = db_session
    ids = await audience(session, 451)
    event_id, target = await pending_event(session)
    assert (await outbox.process_pending(session, limit=1))["processed"] == 1
    assert len(await notices(session, target)) == 50
    row = await session.get(DomainEventOutbox, event_id)
    assert row.status == "pending" and row.attempts == 0 and row.recipient_cursor == ids[49]
    for _ in range(9):
        await outbox.process_pending(session, limit=1)
    assert len(await notices(session, target)) == 451
    row = await session.get(DomainEventOutbox, event_id)
    assert row.status == "completed" and row.attempts == 1 and row.claim_token is None
    assert (await outbox.process_pending(session))["processed"] == 0


@pytest.mark.parametrize("change", ["user", "role", "request"])
async def test_later_page_rechecks_current_recipient_and_request(db_session, change):
    session = db_session
    ids = await audience(session, 55)
    event_id, target = await pending_event(session)
    await outbox.process_pending(session, limit=1)
    if change == "user":
        await session.execute(update(User).where(User.id == ids[-1]).values(status="inactive"))
    elif change == "role":
        await session.execute(
            update(UserCompanyRole)
            .where(UserCompanyRole.user_id == ids[-1])
            .values(status="inactive")
        )
    else:
        await session.execute(
            update(OriginalAccessRequest)
            .where(OriginalAccessRequest.id == target)
            .values(status="rejected")
        )
    await session.commit()
    await outbox.process_pending(session)
    rows = await notices(session, target)
    assert len(rows) == (50 if change == "request" else 54)
    assert ids[-1] not in {r.recipient_user_id for r in rows}
    assert (await session.get(DomainEventOutbox, event_id)).status == "completed"


async def test_ops_pages_share_one_audience_and_stable_original_hour(db_session):
    session = db_session
    await audience(session, 123, admins=True)
    await alert.ensure_default_rules(session)
    rule_id = await session.scalar(select(AlertRule.id).limit(1))
    fact = await audit.record_system_event(
        session,
        log_type=AuditLogType.operation,
        action="ops.alert_triggered",
        trace_id="synthetic",
        target_type="alert_rule",
        target_id=rule_id,
        extra={"count": 1, "threshold": 1},
    )
    await session.flush()
    fact_id = fact.id
    await operation_events.publish_ops_signal(
        session,
        signal="index_failed_backlog",
        count=1,
        hour_bucket="2026010100",
        audit_event_id=fact_id,
        alert_rule_id=rule_id,
    )
    await session.commit()
    for expected in (50, 100, 123):
        assert (await outbox.process_pending(session, limit=1))["processed"] == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(NotificationRecord)
                .where(NotificationRecord.audit_event_id == fact_id)
            )
            == expected
        )
    business = list(await session.scalars(select(BusinessNotification)))
    assert len(business) == 123
    assert all(r.dedup_key.endswith(":2026010100") for r in business)


async def test_projection_failure_rolls_back_page_but_keeps_prior_progress(db_session, monkeypatch):
    session = db_session
    ids = await audience(session, 65)
    event_id, target = await pending_event(session)
    await outbox.process_pending(session, limit=1)
    real = outbox._dispatch

    async def fail_after_projection(*args):
        await real(*args)
        await args[0].flush()
        raise RuntimeError("sensitive detail must not escape")

    monkeypatch.setattr(outbox, "_dispatch", fail_after_projection)
    assert (await outbox.process_pending(session, limit=1))["failed"] == 1
    assert len(await notices(session, target)) == 50
    row = await session.get(DomainEventOutbox, event_id)
    assert row.recipient_cursor == ids[49] and row.last_error_detail == "RuntimeError"
    row.available_at = utc_now() - timedelta(seconds=1)
    await session.commit()
    monkeypatch.setattr(outbox, "_dispatch", real)
    await outbox.process_pending(session)
    assert len(await notices(session, target)) == 65


async def test_page_timeout_rolls_back_and_backs_off(db_session, monkeypatch):
    session = db_session
    await audience(session, 2)
    event_id, target = await pending_event(session)
    real = outbox._dispatch

    async def stalled(session, row):
        result = await real(session, row)
        await session.flush()
        await asyncio.sleep(10)
        return result

    monkeypatch.setattr(outbox, "PAGE_SECONDS", 0.03)
    monkeypatch.setattr(outbox, "_dispatch", stalled)
    assert (await outbox.process_pending(session, limit=1))["failed"] == 1
    assert len(await notices(session, target)) == 0
    row = await session.get(DomainEventOutbox, event_id)
    assert row.status == "failed" and row.last_error_detail == "TimeoutError"
    assert not await outbox.has_ready(session)


async def test_last_abandoned_attempt_becomes_terminal(db_session):
    session = db_session
    event_id, _ = await pending_event(session)
    row = await session.get(DomainEventOutbox, event_id)
    row.status = "processing"
    row.attempts = outbox.MAX_ATTEMPTS
    row.claim_token = str(uuid.uuid4())
    row.claimed_at = utc_now() - timedelta(seconds=outbox.LEASE_SECONDS + 1)
    await session.commit()
    assert await outbox.process_pending(session) == {"processed": 0, "failed": 1}
    row = await session.get(DomainEventOutbox, event_id)
    assert row.status == "failed" and row.claim_token is None
    assert row.last_error_code == "event_consumer_exhausted"
    assert not await outbox.has_ready(session)


async def test_uncommitted_caller_writes_are_never_persisted(db_session):
    user = await db_session.get(User, USER_CONSULTANT)
    user.name = "Uncommitted"
    with pytest.raises(ValueError, match="committed_changes"):
        await outbox.process_pending(db_session)
    await db_session.rollback()


@pytest.mark.parametrize("assigned_active", [True, False])
async def test_project_assignment_is_checked_before_recipient_pagination(
    db_session, assigned_active
):
    session = db_session
    ids = await audience(session, 55)
    await session.execute(
        update(ProjectMember)
        .where(ProjectMember.project_id == PROJECT_ALPHA)
        .values(status="inactive")
    )
    session.add_all(
        ProjectMember(
            project_id=PROJECT_ALPHA,
            user_id=u,
            project_role="project_manager",
            status="inactive" if u == ids[-1] and not assigned_active else "active",
        )
        for u in ids
    )
    review = await session.get(ReviewTask, REVIEW_SEED)
    review.target_project_id = PROJECT_ALPHA
    review.reviewer_user_id = ids[-1]
    review.status = "pending_reviewer"
    event = await domain_events.publish(
        session,
        domain_events.DomainEvent(
            event_type=domain_events.REVIEW_ACTION_REQUIRED,
            aggregate_type="review",
            aggregate_id=review.id,
            payload={},
            idempotency_key=f"project-page:{review.id}",
        ),
    )
    event_id = event.id
    await session.commit()
    await outbox.process_pending(session, limit=1)
    assert len(await notices(session, REVIEW_SEED)) == (1 if assigned_active else 50)
    await outbox.process_pending(session)
    rows = await notices(session, REVIEW_SEED)
    assert {r.recipient_user_id for r in rows} == ({ids[-1]} if assigned_active else set(ids[:-1]))
    assert (await session.get(DomainEventOutbox, event_id)).status == "completed"


async def test_poison_event_exhausts_bounded_retries_without_hiding_later_event(db_session):
    session = db_session
    await audience(session, 1)
    poison = DomainEventOutbox(
        event_type="unsupported",
        aggregate_type="synthetic",
        aggregate_id=uuid.uuid4(),
        payload={},
        idempotency_key="poison",
        status="pending",
    )
    session.add(poison)
    await session.commit()
    poison_id = poison.id
    valid_id, target = await pending_event(session)
    await outbox.process_pending(session)
    assert (await session.get(DomainEventOutbox, valid_id)).status == "completed"
    assert len(await notices(session, target)) == 1
    for _ in range(outbox.MAX_ATTEMPTS - 1):
        row = await session.get(DomainEventOutbox, poison_id)
        row.available_at = utc_now() - timedelta(seconds=1)
        await session.commit()
        assert (await outbox.process_pending(session))["failed"] == 1
    row = await session.get(DomainEventOutbox, poison_id)
    assert row.attempts == outbox.MAX_ATTEMPTS and row.status == "failed"
    assert not await outbox.has_ready(session)

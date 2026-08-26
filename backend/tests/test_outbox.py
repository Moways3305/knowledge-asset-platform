"""Transactional, retry and idempotency guarantees for the durable outbox."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.utils import utc_now
from app.models.notification import BusinessNotification
from app.models.outbox import DomainEventOutbox
from app.models.review import ReviewTask
from app.seed.dev_seed import PROJECT_ALPHA, REVIEW_SEED, USER_CONSULTANT
from app.services import domain_events, notification_event_consumers, outbox


def _review_event() -> domain_events.DomainEvent:
    return domain_events.DomainEvent(
        event_type=domain_events.REVIEW_ACTION_REQUIRED,
        aggregate_type="review",
        aggregate_id=REVIEW_SEED,
        payload=domain_events.safe_payload(
            review_id=REVIEW_SEED,
            project_id=PROJECT_ALPHA,
            review_type="material_to_asset",
            status="pending_reviewer",
        ),
        idempotency_key=f"test-review-action:{REVIEW_SEED}",
    )


async def test_outbox_is_committed_with_domain_transaction_and_not_before(db_session):
    await domain_events.publish(db_session, _review_event())
    await db_session.rollback()
    assert (await db_session.scalar(select(func.count()).select_from(DomainEventOutbox))) == 0

    await domain_events.publish(db_session, _review_event())
    await db_session.commit()
    assert (await db_session.scalar(select(func.count()).select_from(BusinessNotification))) == 0


async def test_repeated_delivery_creates_one_notification(db_session):
    event = await domain_events.publish(db_session, _review_event())
    event_id = event.id
    await db_session.commit()

    assert await outbox.process_pending(db_session) == {"processed": 1, "failed": 0}
    first_count = await db_session.scalar(
        select(func.count())
        .select_from(BusinessNotification)
        .where(BusinessNotification.target_id == REVIEW_SEED)
    )
    assert first_count == 1

    event = await db_session.get(DomainEventOutbox, event_id)
    event.status = "pending"
    event.available_at = utc_now()
    event.processed_at = None
    await db_session.commit()
    assert await outbox.process_pending(db_session) == {"processed": 1, "failed": 0}
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(BusinessNotification)
            .where(BusinessNotification.target_id == REVIEW_SEED)
        )
        == 1
    )


async def test_failed_consumer_is_observable_and_stale_claim_recovers(db_session, monkeypatch):
    event = await domain_events.publish(db_session, _review_event())
    event_id = event.id
    await db_session.commit()
    real_dispatch = outbox._dispatch

    async def fail_once(*_args, **_kwargs):
        raise RuntimeError("sensitive downstream detail")

    monkeypatch.setattr(outbox, "_dispatch", fail_once)
    assert await outbox.process_pending(db_session) == {"processed": 0, "failed": 1}
    failed = await db_session.get(DomainEventOutbox, event_id)
    assert failed.status == "failed"
    assert failed.attempts == 1
    assert failed.last_error_code == "event_consumer_failed"
    assert failed.last_error_detail == "RuntimeError"
    assert "sensitive" not in failed.last_error_detail

    failed.status = "processing"
    failed.claimed_at = utc_now() - timedelta(seconds=outbox.LEASE_SECONDS + 1)
    failed.available_at = utc_now() - timedelta(seconds=1)
    await db_session.commit()
    monkeypatch.setattr(outbox, "_dispatch", real_dispatch)
    assert await outbox.process_pending(db_session) == {"processed": 1, "failed": 0}
    recovered = await db_session.get(DomainEventOutbox, event_id)
    assert recovered.status == "completed"
    assert recovered.attempts == 2


async def test_event_contract_rejects_sensitive_payload_fields(db_session):
    with pytest.raises(ValueError, match="unsupported fields"):
        await domain_events.publish(
            db_session,
            domain_events.DomainEvent(
                event_type=domain_events.INGEST_CONFIRMED,
                aggregate_type="ingest_task",
                aggregate_id=REVIEW_SEED,
                payload={"task_id": str(REVIEW_SEED), "storage_path": "/secret"},
                idempotency_key="invalid-sensitive-event",
            ),
        )


async def test_advertised_event_without_aggregate_is_failed_not_silently_completed(db_session):
    event = await domain_events.publish(
        db_session,
        domain_events.DomainEvent(
            event_type=domain_events.REVIEW_DECIDED,
            aggregate_type="review",
            aggregate_id=uuid.uuid4(),
            payload=domain_events.safe_payload(status="approved", decision="approved"),
            idempotency_key="test-missing-review-decision",
        ),
    )
    event_id = event.id
    await db_session.commit()

    assert await outbox.process_pending(db_session, limit=1) == {"processed": 0, "failed": 1}
    failed = await db_session.get(DomainEventOutbox, event_id)
    assert failed.status == "failed"
    assert failed.last_error_code == "event_consumer_failed"
    assert failed.last_error_detail == "LookupError"


async def test_every_advertised_notification_event_has_an_explicit_handler(monkeypatch):
    aggregate = object()

    class FakeSession:
        async def get(self, _model, _aggregate_id):
            return aggregate

    expected = {
        domain_events.REVIEW_ACTION_REQUIRED: "notify_review_pending",
        domain_events.REVIEW_DECIDED: "notify_review_decided",
        domain_events.INGEST_CONFIRMED: "notify_ingest_confirmed",
        domain_events.INGEST_FAILED: "notify_ingest_failed",
        domain_events.ORIGINAL_ACCESS_REQUESTED: "notify_original_access_pending",
        domain_events.ORIGINAL_ACCESS_DECIDED: "notify_original_access_decided",
        domain_events.INDEX_STATUS_CHANGED: "notify_index_status_changed",
        domain_events.OPERATION_JOB_FINISHED: "notify_operation_job_finished",
        domain_events.OPS_SIGNAL_RAISED: "notify_ops_signal",
    }
    assert set(expected) | {domain_events.LOCAL_NOTIFICATION_REQUESTED} == set(
        notification_event_consumers.NOTIFICATION_EVENT_TYPES
    )
    mocks = {}
    for function_name in expected.values():
        mock = AsyncMock()
        monkeypatch.setattr(notification_event_consumers.notifications, function_name, mock)
        mocks[function_name] = mock
    ops_admin_consumer = AsyncMock()
    monkeypatch.setattr(
        notification_event_consumers,
        "_consume_ops_admin_alert",
        ops_admin_consumer,
    )
    local_notification_consumer = AsyncMock()
    monkeypatch.setattr(
        notification_event_consumers,
        "_consume_local_notification",
        local_notification_consumer,
    )

    for event_type, function_name in expected.items():
        event = DomainEventOutbox(
            event_type=event_type,
            aggregate_type="test",
            aggregate_id=REVIEW_SEED,
            payload={
                "status": "indexed",
                "signal": "index_failed_backlog",
                "count": "1",
                "audit_event_id": str(REVIEW_SEED),
                "alert_rule_id": str(REVIEW_SEED),
            },
            idempotency_key=f"handler:{event_type}",
            status="processing",
            attempts=1,
            available_at=utc_now(),
            created_at=utc_now(),
        )
        await notification_event_consumers.consume_notification_event(
            cast(AsyncSession, FakeSession()), event
        )
        mocks[function_name].assert_awaited_once()
    ops_admin_consumer.assert_awaited_once()

    local_event = DomainEventOutbox(
        event_type=domain_events.LOCAL_NOTIFICATION_REQUESTED,
        aggregate_type="knowledge_asset",
        aggregate_id=REVIEW_SEED,
        payload={
            "notice_type": "lifecycle_archived",
            "recipient_id": str(REVIEW_SEED),
            "asset_id": str(REVIEW_SEED),
            "audit_event_id": str(REVIEW_SEED),
        },
        idempotency_key="handler:local-notification",
        status="processing",
        attempts=1,
        available_at=utc_now(),
        created_at=utc_now(),
    )
    await notification_event_consumers.consume_notification_event(
        cast(AsyncSession, FakeSession()), local_event
    )
    local_notification_consumer.assert_awaited_once()


async def test_review_decided_event_creates_one_submitter_update(db_session):
    task = await db_session.get(ReviewTask, REVIEW_SEED)
    task.status = "approved"
    event = await domain_events.publish(
        db_session,
        domain_events.DomainEvent(
            event_type=domain_events.REVIEW_DECIDED,
            aggregate_type="review",
            aggregate_id=task.id,
            payload=domain_events.safe_payload(
                review_id=task.id,
                project_id=task.target_project_id,
                decision=task.status,
                status=task.status,
            ),
            idempotency_key=f"test-review-decided:{task.id}:{task.status}",
        ),
    )
    event_key = event.idempotency_key
    task_id = task.id
    await db_session.commit()

    assert await outbox.process_pending(db_session) == {"processed": 1, "failed": 0}
    rows = list(
        (
            await db_session.execute(
                select(BusinessNotification).where(
                    BusinessNotification.event_type == "review.decided",
                    BusinessNotification.target_id == task_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].recipient_user_id == USER_CONSULTANT
    assert rows[0].dedup_key == event_key

"""Lease-based, retryable and idempotent domain-event outbox dispatcher."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.utils import utc_now
from app.models.outbox import DomainEventOutbox
from app.services.notification_event_consumers import (
    NOTIFICATION_EVENT_TYPES,
    consume_notification_event,
)

MAX_ATTEMPTS = 8
LEASE_SECONDS = 300
MAX_BATCH = 100


async def _claim_one(session: AsyncSession) -> DomainEventOutbox | None:
    now = utc_now()
    stale_before = now - timedelta(seconds=LEASE_SECONDS)
    stmt = (
        select(DomainEventOutbox)
        .where(
            DomainEventOutbox.attempts < MAX_ATTEMPTS,
            DomainEventOutbox.available_at <= now,
            or_(
                DomainEventOutbox.status.in_(("pending", "failed")),
                (DomainEventOutbox.status == "processing")
                & (DomainEventOutbox.claimed_at < stale_before),
            ),
        )
        .order_by(DomainEventOutbox.created_at, DomainEventOutbox.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        await session.rollback()
        return None
    row.status = "processing"
    row.claimed_at = now
    row.attempts += 1
    row.last_error_code = None
    row.last_error_detail = None
    await session.commit()
    return row


async def _dispatch(session: AsyncSession, row: DomainEventOutbox) -> None:
    if row.event_type in NOTIFICATION_EVENT_TYPES:
        await consume_notification_event(session, row)
        return
    raise ValueError("unsupported_event_type")


async def process_pending(session: AsyncSession, *, limit: int = MAX_BATCH) -> dict[str, int]:
    processed = 0
    failed = 0
    for _ in range(max(0, min(limit, MAX_BATCH))):
        row = await _claim_one(session)
        if row is None:
            break
        event_id = row.id
        try:
            await _dispatch(session, row)
            row.status = "completed"
            row.processed_at = utc_now()
            row.claimed_at = None
            await session.commit()
            processed += 1
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            failed_row = await session.get(DomainEventOutbox, event_id, with_for_update=True)
            if failed_row is not None:
                failed_row.status = "failed"
                failed_row.claimed_at = None
                failed_row.available_at = utc_now() + timedelta(
                    seconds=min(300, 2 ** min(failed_row.attempts, 8))
                )
                failed_row.last_error_code = "event_consumer_failed"
                failed_row.last_error_detail = type(exc).__name__[:120]
                await session.commit()
            failed += 1
    return {"processed": processed, "failed": failed}

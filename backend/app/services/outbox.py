"""Fenced, bounded database-only notification projection.

The claim commits first. Each recipient page then locks that exact token and
commits notification rows, cursor and event state together. No provider call is
allowed here; external delivery has its own queue and ownership protocol.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.utils import utc_now
from app.models.outbox import DomainEventOutbox
from app.services.notification_event_consumers import (
    NOTIFICATION_EVENT_TYPES,
    consume_notification_event,
)
from app.services.notification_recipients import RecipientPage

MAX_ATTEMPTS = 8
LEASE_SECONDS = 300
MAX_BATCH = 100
BATCH_SECONDS = 2.0  # Checked between pages; not a hard SQL deadline.
PAGE_SECONDS = 5.0  # Roll back a stalled projection, never commit partial notices.


def _ready(now):
    stale = (DomainEventOutbox.status == "processing") & or_(
        DomainEventOutbox.claimed_at.is_(None),
        DomainEventOutbox.claimed_at < now - timedelta(seconds=LEASE_SECONDS),
    )
    return (
        DomainEventOutbox.available_at <= now,
        or_(
            (DomainEventOutbox.attempts < MAX_ATTEMPTS)
            & DomainEventOutbox.status.in_(("pending", "failed")),
            stale,  # Final abandoned attempt must become observably terminal.
        ),
    )


async def has_ready(session: AsyncSession) -> bool:
    result = bool(
        await session.scalar(
            select(select(DomainEventOutbox.id).where(*_ready(utc_now())).exists())
        )
    )
    await session.rollback()
    return result


async def _claim_one(session: AsyncSession) -> DomainEventOutbox | None:
    now = utc_now()
    stmt = (
        select(DomainEventOutbox)
        .where(*_ready(now))
        # A completed page yields to already-ready events, including new small ones.
        .order_by(
            DomainEventOutbox.available_at, DomainEventOutbox.created_at, DomainEventOutbox.id
        )
        .with_for_update(skip_locked=True)
        .limit(1)
        .execution_options(populate_existing=True)
    )
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        await session.rollback()
        return None
    if row.attempts >= MAX_ATTEMPTS:
        row.status = "failed"
        row.claim_token = None
        row.claimed_at = None
        row.last_error_code = "event_consumer_exhausted"
        row.last_error_detail = None
        await session.commit()
        return row
    row.status = "processing"
    row.claimed_at = now
    row.claim_token = str(uuid.uuid4())
    row.attempts += 1
    row.last_error_code = None
    row.last_error_detail = None
    await session.commit()
    return row


async def _dispatch(session: AsyncSession, row: DomainEventOutbox) -> RecipientPage:
    if row.event_type in NOTIFICATION_EVENT_TYPES:
        page = RecipientPage(after=row.recipient_cursor)
        await consume_notification_event(session, row, page=page)
        return page
    raise ValueError("unsupported_event_type")


async def _owned(session, event_id, token):
    return await session.scalar(
        select(DomainEventOutbox)
        .where(
            DomainEventOutbox.id == event_id,
            DomainEventOutbox.claim_token == token,
            DomainEventOutbox.status == "processing",
        )
        # Unlike claiming a new event, an owned projection must wait for a
        # transient lock. SKIP LOCKED here could strand its own durable claim.
        # Both callers bound this wait with PAGE_SECONDS.
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def _record_failure(session, event_id, token, exc):
    row = await _owned(session, event_id, token)
    if row is None:
        await session.rollback()
        return False
    row.status = "failed"
    row.claim_token = None
    row.claimed_at = None
    row.available_at = utc_now() + timedelta(seconds=min(300, 2 ** min(row.attempts, 8)))
    row.last_error_code = "event_consumer_failed"
    row.last_error_detail = type(exc).__name__[:120]
    await session.commit()
    return True


async def _consume_page(session, event_id, token):
    row = await _owned(session, event_id, token)
    if row is None:
        await session.rollback()
        return False
    page = await _dispatch(session, row)
    row.recipient_cursor = page.cursor
    row.status = "pending" if page.has_more else "completed"
    row.processed_at = None if page.has_more else utc_now()
    row.available_at = utc_now()
    row.claimed_at = None
    row.claim_token = None
    if page.has_more:
        row.attempts = 0
    await session.commit()
    return True


async def process_pending(session: AsyncSession, *, limit: int = MAX_BATCH) -> dict[str, int]:
    """Process bounded pages; counts are committed pages and failed attempts.

    Successful partial pages reset the per-page retry budget. Progress cannot use up
    the failure budget of a large audience. Cancellation rolls back the page while
    retaining the durable claim for lease recovery.
    """
    if session.new or session.dirty or session.deleted:
        raise ValueError("outbox_requires_committed_changes")
    await session.rollback()
    processed = 0
    failed = 0
    deadline = time.monotonic() + BATCH_SECONDS
    for _ in range(max(0, min(limit, MAX_BATCH))):
        if time.monotonic() >= deadline:
            break
        row = await _claim_one(session)
        if row is None:
            break
        if row.status == "failed":
            failed += 1
            continue
        event_id, token = row.id, row.claim_token
        try:
            processed += int(
                await asyncio.wait_for(
                    _consume_page(session, event_id, token),
                    timeout=PAGE_SECONDS,
                )
            )
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            try:
                failed += int(
                    await asyncio.wait_for(
                        _record_failure(session, event_id, token, exc),
                        timeout=PAGE_SECONDS,
                    )
                )
            except BaseException:
                await session.rollback()
                raise
        except BaseException:
            await session.rollback()
            raise
    return {"processed": processed, "failed": failed}

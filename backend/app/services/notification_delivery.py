"""Short transactions around bounded, lease-owned external notification delivery.

The external send and the database commit cannot be atomic. If a worker dies after
the provider accepts a message, a later attempt may send it again. Delivery is
bounded at-least-once, not exactly-once; a token only fences local ownership and
writeback. Deployments must drain old dispatchers before starting this protocol.
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Generic, TypeVar

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.utils import utc_now
from app.models.lifecycle import NotificationRecord
from app.models.notification import BusinessNotification
from app.services.wecom_client import WeComError

Row = TypeVar("Row", BusinessNotification, NotificationRecord)
MAX_ATTEMPTS = 3
LEASE_SECONDS = 120
SEND_TIMEOUT_SECONDS = 60
BATCH_SECONDS = 60
RETRY_SECONDS = 120  # Preserve the periodic dispatch cadence even with overlapping tasks.
MAX_BATCH = 100


@dataclass(frozen=True)
class Message:
    recipient: str
    title: str
    content: str


@dataclass(frozen=True)
class Failure:
    code: str
    terminal: bool = False
    expired: bool = False


@dataclass(frozen=True)
class Policy(Generic[Row]):
    model: type[Row]
    status: str
    attempts: str
    failure: str
    delivered: str
    prepare: Callable[[AsyncSession, Row], Awaitable[Message | Failure]]
    audit: Callable[[AsyncSession, Row, bool, str | None], Awaitable[None]]


def _safe_failure(exc: WeComError) -> Failure:
    allowed = {
        "recipient_unavailable",
        "wecom_network_error",
        "wecom_token_failed",
        "wecom_no_agent_id",
        "wecom_not_configured",
        "delivery_outcome_unknown",
    }
    code = exc.code
    if code not in allowed and re.fullmatch(r"wecom_msg_[0-9]{1,10}", code) is None:
        code = "delivery_failed"
    return Failure(code)


def _ready_query(model: type[Row], status_name: str, attempts_name: str):
    now = utc_now()
    return (
        select(model)
        .where(
            model.channel == "wecom",
            getattr(model, status_name).in_(("pending", "failed")),
            or_(model.delivery_until.is_(None), model.delivery_until <= now),
            or_(model.delivery_available_at.is_(None), model.delivery_available_at <= now),
            or_(getattr(model, attempts_name) < MAX_ATTEMPTS, model.delivery_token.is_not(None)),
        )
        .order_by(model.created_at, model.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )


async def has_ready(session: AsyncSession) -> bool:
    """Check immediately claimable work, excluding backoff and another owner's locks.

    This is a scheduling hint, not a claim. Release the probe's locks/connection
    before publishing the continuation; the consumer rechecks every condition.
    """
    if session.new or session.dirty or session.deleted:
        raise ValueError("notification_readiness_requires_committed_changes")
    try:
        for query in (
            _ready_query(NotificationRecord, "send_status", "send_attempts"),
            _ready_query(BusinessNotification, "delivery_status", "delivery_attempts"),
        ):
            if await session.scalar(query) is not None:
                return True
        return False
    finally:
        await session.rollback()


async def dispatch(
    session: AsyncSession, *, policy: Policy[Row], sender, trace_id: str | None, limit: int
) -> dict[str, int]:
    """Own fresh per-item sessions; never retain a connection while sending.

    Callers must commit their notification creation first. An existing read
    transaction is released, but unrelated pending writes are never committed.
    """
    if session.new or session.dirty or session.deleted:
        raise ValueError("notification_dispatch_requires_committed_changes")
    await session.rollback()
    sessions = async_sessionmaker(session.bind, expire_on_commit=False)
    result = {"processed": 0, "sent": 0, "failed": 0, "expired": 0}
    deadline = time.monotonic() + BATCH_SECONDS
    model = policy.model
    for _ in range(max(0, min(limit, MAX_BATCH))):
        if time.monotonic() >= deadline:
            break
        async with sessions() as claim:
            row = await claim.scalar(_ready_query(model, policy.status, policy.attempts))
            if row is None:
                break
            attempt = getattr(row, policy.attempts)
            if attempt >= MAX_ATTEMPTS:
                prepared: Message | Failure = Failure("delivery_outcome_unknown", terminal=True)
            else:
                setattr(row, policy.attempts, attempt + 1)
                # Fresh identities and target facts on every attempt, immediately
                # before dispatch, including recipients changed since a prior send.
                prepared = await policy.prepare(claim, row)
            row_id, token = row.id, str(uuid.uuid4())
            row.delivery_token = token
            row.delivery_until = utc_now() + timedelta(seconds=LEASE_SECONDS)
            await claim.commit()
        result["processed"] += 1
        failure = prepared if isinstance(prepared, Failure) else None
        if isinstance(prepared, Message):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # No external attempt was made: return the claim without consuming
                # a retry or auditing a fictitious upstream failure.
                async with sessions() as release:
                    row = await release.scalar(
                        select(model)
                        .where(model.id == row_id, model.delivery_token == token)
                        .with_for_update()
                    )
                    if row is not None:
                        setattr(row, policy.attempts, getattr(row, policy.attempts) - 1)
                        row.delivery_token = None
                        row.delivery_until = None
                        await release.commit()
                result["processed"] -= 1
                break
            try:
                await asyncio.wait_for(
                    sender.send(
                        wecom_user_id=prepared.recipient,
                        title=prepared.title,
                        content=prepared.content,
                        trace_id=trace_id,
                    ),
                    timeout=min(SEND_TIMEOUT_SECONDS, remaining),
                )
            except asyncio.TimeoutError:
                # The provider might have accepted the request before timing out.
                failure = Failure("delivery_outcome_unknown")
            except WeComError as exc:
                failure = _safe_failure(exc)
            except Exception:  # noqa: BLE001 - no provider payload in state or audit
                failure = Failure("delivery_outcome_unknown")
        async with sessions() as finish:
            row = await finish.scalar(
                select(model)
                .where(model.id == row_id, model.delivery_token == token)
                .with_for_update()
            )
            if row is None:
                continue  # A reclaimed lease owns both state and audit now.
            setattr(row, policy.status, "failed" if failure else "sent")
            setattr(row, policy.failure, failure.code if failure else None)
            if failure is None:
                setattr(row, policy.delivered, utc_now())
            elif failure.terminal:
                setattr(row, policy.attempts, MAX_ATTEMPTS)
            row.delivery_token = None
            row.delivery_until = None
            row.delivery_available_at = (
                utc_now() + timedelta(seconds=RETRY_SECONDS) if failure else None
            )
            await policy.audit(finish, row, failure is not None, trace_id)
            await finish.commit()
            result[
                "expired" if failure and failure.expired else "failed" if failure else "sent"
            ] += 1
    return result

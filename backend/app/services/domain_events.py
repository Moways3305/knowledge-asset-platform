"""Stable, minimal domain-event contracts written to the transactional outbox."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.utils import utc_now
from app.models.outbox import DomainEventOutbox

REVIEW_ACTION_REQUIRED = "ReviewActionRequired"
REVIEW_DECIDED = "ReviewDecided"
INGEST_CONFIRMED = "IngestConfirmed"
INGEST_FAILED = "IngestFailed"
ORIGINAL_ACCESS_REQUESTED = "OriginalAccessRequested"
ORIGINAL_ACCESS_DECIDED = "OriginalAccessDecided"
INDEX_STATUS_CHANGED = "IndexStatusChanged"
OPERATION_JOB_FINISHED = "OperationJobFinished"
OPS_SIGNAL_RAISED = "OpsSignalRaised"
LOCAL_NOTIFICATION_REQUESTED = "LocalNotificationRequested"

_ALLOWED_PAYLOADS: dict[str, frozenset[str]] = {
    REVIEW_ACTION_REQUIRED: frozenset({"review_id", "project_id", "review_type", "status"}),
    REVIEW_DECIDED: frozenset({"review_id", "project_id", "decision", "status"}),
    INGEST_CONFIRMED: frozenset({"task_id", "asset_id", "project_id", "status"}),
    INGEST_FAILED: frozenset({"task_id", "project_id", "status"}),
    ORIGINAL_ACCESS_REQUESTED: frozenset({"request_id", "project_id", "status"}),
    ORIGINAL_ACCESS_DECIDED: frozenset({"request_id", "project_id", "decision", "status"}),
    INDEX_STATUS_CHANGED: frozenset({"asset_id", "version_id", "project_id", "status"}),
    OPERATION_JOB_FINISHED: frozenset({"job_id", "status", "operation_type"}),
    OPS_SIGNAL_RAISED: frozenset(
        {"signal", "count", "hour_bucket", "audit_event_id", "alert_rule_id"}
    ),
    LOCAL_NOTIFICATION_REQUESTED: frozenset(
        {"notice_type", "recipient_id", "asset_id", "audit_event_id"}
    ),
}
_FORBIDDEN_KEY_PARTS = {
    "content",
    "text",
    "path",
    "secret",
    "token",
    "weknora",
    "storage",
    "chunk",
    "file_name",
}


@dataclass(frozen=True, slots=True)
class DomainEvent:
    event_type: str
    aggregate_type: str
    aggregate_id: uuid.UUID
    payload: dict[str, str | None]
    idempotency_key: str


def _validate(event: DomainEvent) -> None:
    allowed = _ALLOWED_PAYLOADS.get(event.event_type)
    if allowed is None:
        raise ValueError(f"unsupported domain event: {event.event_type}")
    if not event.payload.keys() <= allowed:
        raise ValueError("domain event payload contains unsupported fields")
    for key, value in event.payload.items():
        normalized = key.casefold()
        if any(part in normalized for part in _FORBIDDEN_KEY_PARTS):
            raise ValueError("domain event payload contains a sensitive field")
        if value is not None and not isinstance(value, str):
            raise ValueError("domain event payload values must be strings or null")
    if len(event.idempotency_key) > 180:
        raise ValueError("domain event idempotency key is too long")


async def publish(session: AsyncSession, event: DomainEvent) -> DomainEventOutbox:
    """Stage an event in the caller's transaction; never commits independently."""
    _validate(event)
    existing = (
        await session.execute(
            select(DomainEventOutbox).where(
                DomainEventOutbox.idempotency_key == event.idempotency_key
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    row_id = uuid.uuid4()
    values = {
        "id": row_id,
        "event_type": event.event_type,
        "aggregate_type": event.aggregate_type,
        "aggregate_id": event.aggregate_id,
        "payload": dict(event.payload),
        "idempotency_key": event.idempotency_key,
        "status": "pending",
        "attempts": 0,
        "available_at": utc_now(),
        "created_at": utc_now(),
    }
    dialect = session.bind.dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as postgresql_insert

        postgresql_stmt = (
            postgresql_insert(DomainEventOutbox)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[DomainEventOutbox.idempotency_key])
        )
        await session.execute(postgresql_stmt)
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        sqlite_stmt = (
            sqlite_insert(DomainEventOutbox)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[DomainEventOutbox.idempotency_key])
        )
        await session.execute(sqlite_stmt)
    else:
        session.add(DomainEventOutbox(**values))
        await session.flush()
    return (
        await session.execute(
            select(DomainEventOutbox).where(
                DomainEventOutbox.idempotency_key == event.idempotency_key
            )
        )
    ).scalar_one()


def safe_payload(**values: Any) -> dict[str, str | None]:
    """Normalize UUID/enums/status facts without accepting rich domain objects."""
    return {
        key: None if value is None else str(getattr(value, "value", value))
        for key, value in values.items()
    }

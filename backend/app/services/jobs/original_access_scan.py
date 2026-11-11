"""Fair, resumable timeout sweeps without retaining a connection between decisions.

A finite pass uses a durable (created_at, id) cursor. Skipped, locked or failed
requests remain pending for human review and the next scheduled pass. Advancing
past them lets later eligible requests run. A process loss before commit rolls
back both the decision and cursor, so resume retries that same position.
"""

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import safe_log_exception
from app.db.utils import utc_now
from app.models.governance_scan import GovernanceScanRun
from app.models.original_access import OriginalAccessRequest
from app.models.permission_rule import PermissionRule
from app.services import original_access
from app.services.jobs import governance_scan
from app.services.permission_rules import access_request_timeout_hours, load_access_policy

NAME = "original_access"
BATCH_SIZE = 100
BATCH_SECONDS = 2.0  # Between decisions; not a SQL execution timeout.
_RULE_KEYS = (
    "access_request_timeout_hours",
    "access_grant_duration_days",
    "company_l1_l2_original_for_business_user",
)
_logger = logging.getLogger(__name__)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _cursor(run):
    value = run.parameters.get("cursor")
    return (_aware(datetime.fromisoformat(value[0])), uuid.UUID(value[1])) if value else None


def _candidates(run, timeout_hours):
    statement = select(OriginalAccessRequest.id, OriginalAccessRequest.created_at).where(
        OriginalAccessRequest.status == "pending",
        OriginalAccessRequest.created_at < run.cutoff_at - timedelta(hours=timeout_hours),
    )
    cursor = _cursor(run)
    if cursor:
        created, request_id = cursor
        statement = statement.where(
            or_(
                OriginalAccessRequest.created_at > created,
                and_(
                    OriginalAccessRequest.created_at == created,
                    OriginalAccessRequest.id > request_id,
                ),
            )
        )
    return statement.order_by(OriginalAccessRequest.created_at, OriginalAccessRequest.id).limit(1)


async def _current_run(session, stamp=None):
    run = await session.scalar(
        select(GovernanceScanRun)
        .where(
            GovernanceScanRun.name == NAME,
            GovernanceScanRun.completed_at.is_(None),
        )
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    if run is not None and (stamp is None or _aware(run.started_at) == _aware(stamp)):
        return run
    await session.rollback()
    return None


def _set_cursor(run, key):
    previous = _cursor(run)
    if previous is None or key > previous:
        run.parameters = {"cursor": [key[0].isoformat(), str(key[1])]}


async def _commit_item(session, run, key):
    _set_cursor(run, key)
    await session.commit()


def _lock_conflict(exc):
    original = getattr(exc, "orig", exc)
    return (getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)) == "55P03"


async def _lock_rules(session):
    # Share locks prevent a rule being disabled/changed between this decision's
    # check and commit. NOWAIT defers to an administrator editing the rules.
    await session.execute(
        select(PermissionRule)
        .where(
            PermissionRule.rule_key.in_(_RULE_KEYS),
        )
        .order_by(PermissionRule.rule_key)
        .with_for_update(read=True, nowait=True)
        .execution_options(populate_existing=True)
    )


async def scan(
    session: AsyncSession,
    *,
    trace_id: str,
    now: datetime | None = None,
    limit: int = BATCH_SIZE,
    resume_only: bool = False,
) -> dict:
    stats: dict = {
        "checked": 0,
        "approved": 0,
        "skipped_confidential": 0,
        "skipped_invalid": 0,
        "errors": 0,
        "deferred_locked": 0,
        "enabled": False,
    }
    started = time.monotonic()
    # Do not freeze permissions for a sweep. Every decision re-reads the rules,
    # asset, requester and roles in its own short transaction.
    timeout = await access_request_timeout_hours(session)
    await session.commit()
    if timeout is None:
        run = await _current_run(session)
        if run is not None:
            run.completed_at = utc_now()
            await session.commit()
        return stats
    stats.update(enabled=True, timeout_hours=timeout)
    run = await governance_scan.begin_cycle(session, NAME, resume_only=resume_only, now=now)
    if run is None:
        return stats
    stamp = run.started_at
    try:
        for _ in range(max(1, min(limit, BATCH_SIZE))):
            if stats["checked"] and time.monotonic() - started >= BATCH_SECONDS:
                break
            if run is None:
                run = await _current_run(session, stamp)
            if run is None:
                break  # Another consumer owns the current decision, or finished it.
            key = None
            try:
                await _lock_rules(session)
                timeout = await access_request_timeout_hours(session)
                if timeout is None:
                    stats["enabled"] = False
                    run.completed_at = utc_now()
                    await session.commit()
                    break
                stats["timeout_hours"] = timeout
                candidate = (await session.execute(_candidates(run, timeout))).first()
                if candidate is None:
                    run.completed_at = utc_now()
                    await session.commit()
                    break
                key = (_aware(candidate.created_at), candidate.id)
                stats["checked"] += 1
                outcome = await original_access._auto_approve_one(
                    session,
                    candidate.id,
                    now=now or utc_now(),
                    days=await original_access._grant_duration_days(session),
                    timeout_hours=timeout,
                    policy=await load_access_policy(session),
                    trace_id=trace_id,
                    commit=False,
                    nonblocking=True,
                )
                await _commit_item(session, run, key)
                stats[outcome] += 1
            except Exception as exc:
                await session.rollback()
                locked = _lock_conflict(exc)
                stats["deferred_locked" if locked else "errors"] += 1
                if not locked:
                    safe_log_exception(
                        _logger,
                        "auto_approve_item_failed",
                        exc,
                        include_summary=False,
                        level=logging.WARNING,
                    )
                if key is None:
                    break  # Rule editing/database failure: no request was examined.
                # A failed/locked item must not starve later requests. It stays
                # pending and is reconsidered on the next scheduled pass.
                run = await _current_run(session, stamp)
                if run is None:
                    break
                await _commit_item(session, run, key)
            run = None
        # Complete without an extra empty message. This check creates no grant;
        # permission changes are re-read again by the next actual decision.
        run = await _current_run(session, stamp)
        if run is not None:
            timeout = await access_request_timeout_hours(session)
            if (
                timeout is None
                or (await session.execute(_candidates(run, timeout))).first() is None
            ):
                run.completed_at = utc_now()
            await session.commit()
    except BaseException:
        await session.rollback()
        raise
    if stats["approved"]:
        await original_access.enqueue_outbox_delivery(session)
    return stats

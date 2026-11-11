"""Bounded scan batches with transactional progress and nonblocking row claims.

Each asset is marked only with the events in the same transaction. Locked or
unprocessed assets keep their old watermark, so they remain in the current cycle.
No cursor can skip them. A fixed cycle time excludes newly created assets and
newly due reviews; those are picked up by the next daily trigger.
"""

import time
import uuid
from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.utils import utc_now
from app.models.governance_scan import GovernanceScanRun
from app.models.knowledge import KnowledgeAsset

BATCH_SIZE = 50
BATCH_SECONDS = 2.0  # Checked between assets, not a hard SQL execution deadline.


async def start_daily_cycles(session: AsyncSession) -> None:
    """Persist both intentions atomically before either scan can be interrupted."""
    names = ("archive", "review")
    existing = set(await session.scalars(select(GovernanceScanRun.name)))
    stamp = utc_now()
    for name in names:
        if name not in existing:
            statement = (
                postgresql_insert(GovernanceScanRun)
                if session.get_bind().dialect.name == "postgresql"
                else sqlite_insert(GovernanceScanRun)
            )
            await session.execute(
                statement.values(
                    name=name, started_at=stamp, cutoff_at=stamp, completed_at=stamp, parameters={}
                ).on_conflict_do_nothing(index_elements=["name"])
            )
    rows = list(
        await session.scalars(
            select(GovernanceScanRun)
            .where(GovernanceScanRun.name.in_(names))
            .order_by(GovernanceScanRun.name)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    )
    if len(rows) != 2 or any(row.completed_at is None for row in rows):
        await session.rollback()
        return
    for row in rows:
        row.started_at = row.cutoff_at = stamp
        row.completed_at = None
        row.parameters = {}
    await session.commit()


async def begin_cycle(
    session: AsyncSession, name: str, *, resume_only: bool, now: datetime | None = None
) -> GovernanceScanRun | None:
    row = await session.scalar(
        select(GovernanceScanRun)
        .where(GovernanceScanRun.name == name)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    if row is None:
        # Distinguish an absent row from another batch's locked row. Never wait
        # on that owner, and don't insert/upsert a row already owned by it.
        exists = await session.scalar(
            select(GovernanceScanRun.name).where(GovernanceScanRun.name == name)
        )
        if exists is not None or resume_only:
            await session.rollback()
            return None
        stamp = utc_now()
        dialect = session.get_bind().dialect.name
        statement = (
            postgresql_insert(GovernanceScanRun)
            if dialect == "postgresql"
            else sqlite_insert(GovernanceScanRun)
        )
        await session.execute(
            statement.values(
                name=name,
                started_at=stamp,
                cutoff_at=now or stamp,
                completed_at=stamp,
                parameters={},
            ).on_conflict_do_nothing(index_elements=["name"])
        )
        row = await session.scalar(
            select(GovernanceScanRun)
            .where(GovernanceScanRun.name == name)
            .with_for_update(skip_locked=True)
        )
    if row is None or (resume_only and row.completed_at is not None):
        await session.rollback()
        return None
    if row.completed_at is not None:
        row.started_at = utc_now()
        row.cutoff_at = now or row.started_at
        row.completed_at = None
        row.parameters = {}
        # Persist the intention before any work. A crash in the very first batch
        # must still be visible to the resume beat, not wait until tomorrow.
        await session.commit()
        row = await session.scalar(
            select(GovernanceScanRun)
            .where(GovernanceScanRun.name == name)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if row is None or row.completed_at is not None:
            await session.rollback()
            return None
    return row


def pending_query(run: GovernanceScanRun, *conditions):
    marker = getattr(KnowledgeAsset, f"{run.name}_scan_checked_at")
    return select(KnowledgeAsset).where(
        KnowledgeAsset.deleted_at.is_(None),
        KnowledgeAsset.created_at <= run.started_at,
        or_(marker.is_(None), marker < run.started_at),
        *conditions,
    )


async def claim_assets(session: AsyncSession, run: GovernanceScanRun, *conditions):
    marker = getattr(KnowledgeAsset, f"{run.name}_scan_checked_at")
    return list(
        await session.scalars(
            pending_query(run, *conditions)
            .order_by(marker.asc().nulls_last(), KnowledgeAsset.id)
            .limit(BATCH_SIZE)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    )


def budget_exhausted(started: float, processed: list[uuid.UUID]) -> bool:
    return bool(processed) and time.monotonic() - started >= BATCH_SECONDS


async def finish_batch(session: AsyncSession, run: GovernanceScanRun, processed, *conditions):
    if processed:
        await session.execute(
            update(KnowledgeAsset)
            .where(KnowledgeAsset.id.in_(processed))
            .values(
                {
                    f"{run.name}_scan_checked_at": run.started_at,
                    "updated_at": KnowledgeAsset.updated_at,
                }
            )
            .execution_options(synchronize_session=False)
        )
    # No row locks here: a row held by an editor still counts as pending.
    remains = await session.scalar(select(pending_query(run, *conditions).exists()))
    if not remains:
        run.completed_at = utc_now()
    await session.commit()


async def has_pending(
    session: AsyncSession, names: tuple[str, ...] = ("archive", "review")
) -> bool:
    result = bool(
        await session.scalar(
            select(GovernanceScanRun.name)
            .where(GovernanceScanRun.name.in_(names), GovernanceScanRun.completed_at.is_(None))
            .limit(1)
        )
    )
    await session.rollback()
    return result

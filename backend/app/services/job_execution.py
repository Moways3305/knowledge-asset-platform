"""Cross-worker ownership that survives business commits and ends on disconnect."""

import hashlib
import uuid
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def try_execution_lock(session: AsyncSession, kind: str, identifier: uuid.UUID) -> bool:
    if session.get_bind().dialect.name != "postgresql":
        return True
    # Use the single-bigint key space, separate from the two-int capacity slots.
    key = int.from_bytes(
        hashlib.blake2b(f"kap:{kind}:{identifier}".encode(), digest_size=8).digest(),
        "big",
        signed=True,
    )
    return bool(await session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key}))


@asynccontextmanager
async def exclusive_execution(session: AsyncSession, kind: str, identifier: uuid.UUID):
    if session.get_bind().dialect.name != "postgresql":
        yield True
        return
    # The owner transaction must be separate: processing commits and rollbacks
    # cannot release ownership halfway through an external call.
    async with AsyncSession(bind=session.bind) as owner:
        try:
            yield await try_execution_lock(owner, kind, identifier)
        finally:
            await owner.rollback()

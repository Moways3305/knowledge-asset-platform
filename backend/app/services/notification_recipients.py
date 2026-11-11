"""Bound a single event's recipient query using a durable UUID cursor."""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

PAGE_SIZE = 50


@dataclass
class RecipientPage:
    after: uuid.UUID | None = None
    cursor: uuid.UUID | None = None
    has_more: bool = False
    queried: bool = False

    async def select(self, session: AsyncSession, statement, column) -> list[uuid.UUID]:
        # One union of eligible recipients per event, not independently paged
        # role queries whose cursors could skip or repeat recipients.
        if self.queried:
            raise ValueError("recipient_page_requires_one_query")
        self.queried = True
        if self.after is not None:
            statement = statement.where(column > self.after)
        rows = list(
            await session.scalars(statement.distinct().order_by(column).limit(PAGE_SIZE + 1))
        )
        self.has_more = len(rows) > PAGE_SIZE
        ids = rows[:PAGE_SIZE]
        self.cursor = ids[-1] if ids else self.after
        return ids

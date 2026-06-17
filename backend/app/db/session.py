"""Async SQLAlchemy engine / session factory.

The engine is created lazily so that importing this module (e.g. during tests
that only hit `/health`) does not require a live database. No connection is
opened until a session is actually used.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    """Create (once) and return the async engine（按配置设连接池，pre_ping 防陈旧连接）。"""
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        future=True,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_recycle=settings.db_pool_recycle,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return a cached async session factory bound to the engine."""
    return async_sessionmaker(bind=get_engine(), expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an async DB session (for future use)."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        yield session

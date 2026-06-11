"""Celery worker 的 async 运行时。

问题：Celery 任务用 `asyncio.run()` 每次新建事件循环，但全局 `get_engine()` 是
`@lru_cache` 的单例——其 asyncpg 连接池绑定在**首个**事件循环上。第二个任务的新循环
复用该池 → `got Future attached to a different loop` / `Event loop is closed`。

修复：每个任务调用**自建一个绑定本次事件循环的 async engine**，跑完即 `dispose()`，
绝不跨循环复用连接池。API（请求路径 / eager）仍用全局 engine（在 app 自己的循环里），
不受影响。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

_T = TypeVar("_T")


def run_task(coro_fn: Callable[[async_sessionmaker[AsyncSession]], Awaitable[_T]]) -> _T:
    """在**全新事件循环 + loop-local engine** 上跑一个 worker 任务体。

    `coro_fn` 接收一个本次专用的 `async_sessionmaker`；任务结束（含异常）后 dispose
    engine。这样多次 `asyncio.run` 各自独立，规避 asyncpg 池跨循环复用崩溃。
    """

    async def _main() -> _T:
        settings = get_settings()
        engine = create_async_engine(settings.database_url, future=True, pool_pre_ping=True)
        maker = async_sessionmaker(bind=engine, expire_on_commit=False)
        try:
            return await coro_fn(maker)
        finally:
            # 释放本次循环上的连接池，避免悬挂到下一个 asyncio.run 的新循环。
            await engine.dispose()

    return asyncio.run(_main())

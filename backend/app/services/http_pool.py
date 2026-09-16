"""Bounded HTTP clients owned by an API lifespan or one worker event loop.

Only stateless upstream calls use this pool: authentication and trace headers
remain request-local, and upstream cookies are never carried between calls.
Unmanaged CLI/test callers retain the short-lived client behavior.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from http.cookiejar import CookieJar, DefaultCookiePolicy

import httpx

_MAX_CLIENTS = 8
_logger = logging.getLogger(__name__)
_LIMITS = httpx.Limits(max_connections=16, max_keepalive_connections=8, keepalive_expiry=15)


class _NoCookies(DefaultCookiePolicy):
    def set_ok(self, cookie, request):
        return False


@dataclass
class _Pool:
    owners: int = 0
    clients: dict[float, httpx.AsyncClient] = field(default_factory=dict)


# Keying by the actual loop (not its id) prevents reuse across asyncio.run calls.
# Entries exist only while a managed lifespan owns them; nothing is made at import.
_pools: dict[asyncio.AbstractEventLoop, _Pool] = {}


@asynccontextmanager
async def outbound_http_pool() -> AsyncIterator[None]:
    loop = asyncio.get_running_loop()
    pool = _pools.setdefault(loop, _Pool())
    pool.owners += 1
    body_failed = False
    try:
        yield
    except BaseException:
        # Includes cancellation: shutdown must not change the task's outcome.
        body_failed = True
        raise
    finally:
        pool.owners -= 1
        if pool.owners == 0:
            del _pools[loop]
            # Attempt every close even if one client fails to shut down.
            try:
                results = await asyncio.gather(
                    *(client.aclose() for client in pool.clients.values()), return_exceptions=True
                )
            except BaseException as exc:
                results = [exc]
            for result in results:
                if isinstance(result, BaseException):
                    if not body_failed:
                        raise result
                    # Never log the exception message/traceback: upstream URLs
                    # or credentials may be embedded in a transport exception.
                    _logger.warning(
                        "outbound_http_pool_close_failed",
                        extra={"error_type": type(result).__name__},
                    )


@asynccontextmanager
async def pooled_http_client(*, timeout: float) -> AsyncIterator[httpx.AsyncClient]:
    pool = _pools.get(asyncio.get_running_loop())
    if pool is None or (timeout not in pool.clients and len(pool.clients) >= _MAX_CLIENTS):
        # No unbounded cache of dynamically configured timeouts.
        async with httpx.AsyncClient(timeout=timeout, limits=_LIMITS) as client:
            yield client
        return
    if timeout not in pool.clients:
        pool.clients[timeout] = httpx.AsyncClient(
            timeout=timeout, limits=_LIMITS, cookies=CookieJar(policy=_NoCookies())
        )
    yield pool.clients[timeout]

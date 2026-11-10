"""Per-worker admission and cancellation for expensive HTTP search operations.

No waiting queue: reject excess work before reading a body or checking out a DB
connection. Limits multiply by the number of API workers/replicas. This is load
shedding, not a distributed user quota or a replacement for authentication.
"""

from __future__ import annotations

import asyncio
import logging
import re
from weakref import WeakKeyDictionary

from anyio import CancelScope
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings
from app.core.trace import generate_trace_id

_logger = logging.getLogger(__name__)
_PATHS = {"/api/v1/knowledge/search", "/api/v1/agent-gateway/tools/knowledge-search"}
_PROJECT_QA = re.compile(r"/api/v1/projects/[^/]+/qa")


class SearchLoadGuard:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._active: WeakKeyDictionary[asyncio.AbstractEventLoop, int] = WeakKeyDictionary()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "").rstrip("/")
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not (path in _PATHS or _PROJECT_QA.fullmatch(path))
        ):
            await self.app(scope, receive, send)
            return
        settings = get_settings()
        loop = asyncio.get_running_loop()
        active = self._active.get(loop, 0)
        if active >= settings.search_concurrency_per_worker:
            _logger.info("search_capacity_rejected", extra={"active": active})
            await self._error(
                scope, receive, send, 503, "search_busy", "检索服务繁忙，请稍后重试。"
            )
            return
        # No await between checking and reserving on this event loop.
        self._active[loop] = active + 1
        try:
            await self._serve(scope, receive, send, settings.search_timeout_seconds)
        finally:
            remaining = self._active[loop] - 1
            if remaining:
                self._active[loop] = remaining
            else:
                del self._active[loop]

    @staticmethod
    async def _error(scope, receive, send, status, reason, message):
        trace_id = scope.get("state", {}).get("trace_id") or generate_trace_id()
        response = JSONResponse(
            {"detail": {"denied_reason": reason, "message": message}},
            status_code=status,
            headers={"Retry-After": "2", "X-Trace-Id": trace_id},
        )
        await response(scope, receive, send)

    async def _serve(self, scope: Scope, receive: Receive, send: Send, timeout: float) -> None:
        # Only this pump reads the upstream channel. A single buffered ASGI
        # message preserves backpressure while the app consumes the body.
        inbox: asyncio.Queue[Message] = asyncio.Queue(maxsize=1)
        disconnected = asyncio.Event()
        started = asyncio.Event()
        complete = False

        async def pump():
            while True:
                message = await receive()
                if message["type"] == "http.disconnect" and not complete:
                    disconnected.set()
                await inbox.put(message)
                if message["type"] == "http.disconnect":
                    return

        async def forward(message: Message):
            nonlocal complete
            if message["type"] == "http.response.start":
                started.set()
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                # Some in-process transports send disconnect immediately after
                # this message. Successful response cleanup must still finish.
                complete = True
            await send(message)

        async def execute():
            # This guard sits inside BaseHTTPMiddleware. Its outer AnyIO task
            # groups use level cancellation, which otherwise repeatedly cancels
            # awaited dependency cleanup. Only this guard cancels the owned
            # operation, once, and awaits it before releasing admission.
            with CancelScope(shield=True):
                await self.app(scope, inbox.get, forward)

        operation = asyncio.create_task(execute())
        reader = asyncio.create_task(pump())
        disconnect = asyncio.create_task(disconnected.wait())
        response_start = asyncio.create_task(started.wait())
        tasks = (operation, reader, disconnect, response_start)
        timed_out = False
        try:
            done, _ = await asyncio.wait(
                tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            # Processing deadline ends when headers start. Never replace an
            # already-started response with a second status line. Disconnect
            # monitoring remains active during response transmission.
            if started.is_set() and not complete and operation not in done:
                done, _ = await asyncio.wait(
                    (operation, reader, disconnect), return_when=asyncio.FIRST_COMPLETED
                )
            if operation in done or complete:
                await asyncio.shield(operation)
            elif disconnected.is_set():
                _logger.info("search_client_disconnected")
            elif reader in done:
                await reader  # Propagate receive failures rather than masking them.
            else:
                _logger.warning("search_request_timeout")
                timed_out = True
        finally:
            # Do not advertise a free slot while DB/HTTP cancellation cleanup
            # is still running. No detached task continues consuming a slot.
            with CancelScope(shield=True):
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        if timed_out and not started.is_set() and not disconnected.is_set():
            await self._error(
                scope, receive, send, 504, "search_timeout", "检索处理超时，请稍后重试。"
            )
        elif disconnected.is_set() and not started.is_set():
            # The socket is gone. Complete the ASGI response for outer middleware
            # (and access logging), avoiding a spurious "No response returned" 500.
            await Response(status_code=499)(scope, receive, send)

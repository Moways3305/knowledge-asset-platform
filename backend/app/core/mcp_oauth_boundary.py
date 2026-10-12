"""Bound unauthenticated OAuth requests before SDK parsing and persistence."""

import asyncio
import time
from collections import OrderedDict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

ENDPOINTS = {"/authorize", "/register", "/token", "/revoke"}


class McpOAuthBoundary(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.windows = OrderedDict()

    async def dispatch(self, request, call_next):
        if request.url.path not in ENDPOINTS:
            return await call_next(request)
        now = time.monotonic()
        key = request.client.host if request.client else "unknown"
        while self.windows and next(iter(self.windows.values()))[0] + 60 <= now:
            self.windows.popitem(last=False)
        if key not in self.windows and len(self.windows) >= 2048:
            return JSONResponse({"error": "temporarily_unavailable"}, status_code=429)
        start, count = self.windows.get(key, (now, 0))
        if start + 60 <= now:
            start, count = now, 0
            self.windows.pop(key, None)
        if count >= 120:
            return JSONResponse({"error": "temporarily_unavailable"}, status_code=429)
        self.windows[key] = (start, count + 1)

        async def read():
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 65536:
                    return None
                chunks.append(chunk)
            return b"".join(chunks)

        try:
            body = await asyncio.wait_for(read(), timeout=10)
        except asyncio.TimeoutError:
            return JSONResponse({"error": "invalid_request"}, status_code=408)
        if body is None or len(request.scope.get("query_string", b"")) > 8192:
            return JSONResponse({"error": "invalid_request"}, status_code=413)
        request._body = body
        return await call_next(request)

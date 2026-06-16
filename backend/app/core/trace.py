"""trace_id middleware skeleton.

Per the API contract, every request carries or is assigned a
trace_id, surfaced via the `X-Trace-Id` header and stored on request.state.
This is the cross-module correlation id; it is NOT an authorization token.
"""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

from app.core.logging import trace_id_var

TRACE_HEADER = "X-Trace-Id"

# 请求访问日志：只记 method / path / status / 耗时 / trace_id——**绝不**记请求体 /
# 响应体 / 查询串 / 业务正文 / 密钥（合规留痕以 audit_events 为准）。
_request_logger = logging.getLogger("app.request")


def generate_trace_id() -> str:
    """Generate a new trace_id."""
    return uuid.uuid4().hex


class TraceIdMiddleware(BaseHTTPMiddleware):
    """Reuse an inbound X-Trace-Id or generate one, and echo it back.

    The trace_id is also placed on `request.state.trace_id` so downstream
    handlers (and future Celery / gateway calls) can propagate it.
    """

    def __init__(self, app: ASGIApp, header_name: str = TRACE_HEADER) -> None:
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get(self.header_name) or generate_trace_id()
        request.state.trace_id = trace_id
        # 绑定到日志上下文：本请求内的服务层日志自动带 trace_id（无需逐条传参）。
        token = trace_id_var.set(trace_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers[self.header_name] = trace_id
            # 结构化访问日志（仅安全字段，无 body / query / 密钥）。
            duration_ms = round((time.perf_counter() - start) * 1000, 1)
            _request_logger.info(
                "request",
                extra={
                    "trace_id": trace_id,
                    "method": request.method,
                    "path": request.url.path,  # 仅路径，不含 query（可能含参数）
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
            return response
        finally:
            trace_id_var.reset(token)


def get_trace_id(request: Request) -> str:
    """Read the trace_id from request state, falling back to a fresh id."""
    return getattr(request.state, "trace_id", None) or generate_trace_id()

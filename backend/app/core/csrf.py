"""CSRF 防护中间件。

只对**cookie 会话**下的 unsafe 请求强制 CSRF 校验，在业务 handler 执行前 fail-closed，
避免失败请求产生任何业务写入 / 业务审计。

强制条件（全部满足才校验）：
- method ∈ {POST, PUT, PATCH, DELETE}；
- 请求带 `kap_session` cookie（即浏览器 cookie 会话）；
- 无 `Authorization` 头（Bearer 外部 Agent / Dify 走 token 鉴权，不依赖 ambient cookie，
  不在 CSRF 范围——加此条确保绝不误伤）；
- path 不在豁免集合（仅 `/api/v1/auth/login`：新用户登录前不可能持有 CSRF token；
  `/api/v1/auth/csrf` 为 GET，安全方法天然不校验）。

非 cookie 会话（dev 的 `X-Dev-User-Id` 回退、Bearer token、无会话）一律放行——它们不暴露
ambient-cookie CSRF 面。校验失败统一返回 403 + 安全 reason_code，不回显 token / cookie 值。

CSRF 失败**不写审计**（避免攻击流量放大审计；依赖 HTTP 访问日志 / metrics——TraceIdMiddleware
已记 method/path/status/trace_id）。校验无状态（仅 HMAC + cookie 派生绑定），不触 DB。
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from app.services.auth_session import SESSION_COOKIE_NAME
from app.services.csrf import verify_csrf_token

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_CSRF_HEADER = "X-CSRF-Token"
# 豁免 path（精确匹配）：登录本身不可能预先持有 CSRF token。
_EXEMPT_PATHS = frozenset({"/api/v1/auth/login"})

_USER_MESSAGE = "请求校验失败，请刷新页面后重试"


class CsrfMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        if self._needs_csrf(request):
            reason = verify_csrf_token(
                request.headers.get(_CSRF_HEADER),
                request.cookies.get(SESSION_COOKIE_NAME),
            )
            if reason is not None:
                # fail-closed：handler 未执行 → 无业务写入 / 无业务审计。
                return JSONResponse(
                    status_code=403,
                    content={"detail": {"denied_reason": reason, "message": _USER_MESSAGE}},
                )
        return await call_next(request)

    @staticmethod
    def _needs_csrf(request: Request) -> bool:
        if request.method not in _UNSAFE_METHODS:
            return False
        # 仅浏览器 cookie 会话受 CSRF 约束。
        if not request.cookies.get(SESSION_COOKIE_NAME):
            return False
        # Bearer 鉴权（外部 Agent / Dify）不依赖 ambient cookie → 不在 CSRF 范围。
        if request.headers.get("authorization"):
            return False
        if request.url.path in _EXEMPT_PATHS:
            return False
        return True

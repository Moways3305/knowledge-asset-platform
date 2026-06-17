"""CSRF token 服务。

**无状态、签名（HMAC-SHA256）、带过期、绑定 session** 的 CSRF token，用于保护 cookie 会话
下的有副作用请求（synchronizer-token 形态：token 经 JSON 下发、前端内存缓存、unsafe 请求经
`X-CSRF-Token` 头回送；不依赖可读 CSRF cookie，避免再下发 httpOnly=false cookie）。

token 形态：`{expiry_epoch}.{nonce}.{sig}`，其中
    sig = HMAC-SHA256(key=CSRF_TOKEN_SECRET, msg=f"{expiry}.{nonce}.{session_binding}")
    session_binding = sha256(raw kap_session token) 十六进制；无会话时为常量 "anon"。

绑定 session 使一个会话签发的 token 不能用于另一会话（也防止 token 跨会话重放）。

安全红线：CSRF token 不是认证凭证；session_binding 经单向 sha256 派生，**绝不**反含
明文 session token / token_hash / cookie 值；secret 仅本模块读取、绝不外泄。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from app.core.config import Settings, get_settings
from app.db.utils import utc_now

# 非 prod 空 secret 的稳定回退常量（仍单向 HMAC；prod 必须显式配置真实 secret）。
_FALLBACK_SECRET = "kap-dev-csrf-token-hmac-fallback"
_ANON_BINDING = "anon"
_NONCE_BYTES = 16


def _secret(settings: Settings | None = None) -> str:
    s = settings or get_settings()
    return (s.csrf_token_secret or "").strip() or _FALLBACK_SECRET


def _ttl_minutes(settings: Settings | None = None) -> int:
    s = settings or get_settings()
    try:
        v = int(s.csrf_token_ttl_minutes)
    except (TypeError, ValueError):
        return 720
    return v if v >= 1 else 720


def _session_binding(session_token: str | None) -> str:
    """把 raw session token 单向派生为绑定值（绝不可逆回 token / cookie 值）。"""
    if not session_token:
        return _ANON_BINDING
    return hashlib.sha256(session_token.encode("utf-8")).hexdigest()


def _sign(expiry: int, nonce: str, binding: str, settings: Settings | None = None) -> str:
    msg = f"{expiry}.{nonce}.{binding}".encode()
    return hmac.new(_secret(settings).encode("utf-8"), msg, hashlib.sha256).hexdigest()


def issue_csrf_token(
    session_token: str | None, *, settings: Settings | None = None
) -> tuple[str, datetime]:
    """签发绑定到当前 session（或 anon）的 CSRF token，返回 (token, expires_at)。"""
    s = settings or get_settings()
    expires_at = utc_now() + timedelta(minutes=_ttl_minutes(s))
    expiry = int(expires_at.timestamp())
    nonce = secrets.token_urlsafe(_NONCE_BYTES)
    binding = _session_binding(session_token)
    sig = _sign(expiry, nonce, binding, settings=s)
    return f"{expiry}.{nonce}.{sig}", expires_at


def verify_csrf_token(
    token: str | None, session_token: str | None, *, settings: Settings | None = None
) -> str | None:
    """校验 CSRF token。成功返回 None；失败返回安全 reason_code（不回显 token 内容）。

    reason_code ∈ {csrf_token_missing, csrf_token_invalid, csrf_token_expired}。
    """
    if not token:
        return "csrf_token_missing"
    parts = token.split(".")
    if len(parts) != 3:
        return "csrf_token_invalid"
    expiry_str, nonce, sig = parts
    try:
        expiry = int(expiry_str)
    except (TypeError, ValueError):
        return "csrf_token_invalid"
    binding = _session_binding(session_token)
    expected = _sign(expiry, nonce, binding, settings=settings)
    # 先恒定时间比对签名，再判过期，避免对无效签名也透出"仅过期"信号。
    if not hmac.compare_digest(sig, expected):
        return "csrf_token_invalid"
    if int(utc_now().timestamp()) > expiry:
        return "csrf_token_expired"
    return None

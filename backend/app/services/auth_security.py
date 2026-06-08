"""登录失败守卫服务。

最小登录失败风控闭环：把失败/成功登录写入 `auth_login_attempts`（仅不可逆 hash + 计数 +
原因码），按 identifier / IP 两个维度做短时锁定 / 限流，并保持统一用户态错误。

不可逆标识：identifier_hash = HMAC-SHA256(key=secret, msg="identifier:" + normalized_email)，
ip_hash 同理（purpose="ip"）。secret 来自 `AUTH_ATTEMPT_HASH_SECRET`，prod 必须配置（缺失
→ /health/config blocker）；非 prod 空值回退稳定常量（仍单向）。

锁定语义：
- identifier 维度：自**最近一次成功登录之后**、在 `auth_failed_window_minutes` 窗口内，
  失败类尝试（failed/locked/rate_limited）数达到 `auth_max_failed_attempts` 且距最近一次
  失败尝试不足 `auth_lockout_minutes` → locked。
- IP 维度：在 `auth_ip_failed_window_minutes` 窗口内失败类尝试数达到
  `auth_ip_max_failed_attempts` → rate_limited。
- 成功登录写 success，后续 identifier 失败计数从该成功之后重新开始。

安全红线：本模块**绝不**返回 / 落库 raw email / password / hash / salt / digest /
session token / OAuth state / cookie / token_hash / 原始 IP。
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models.auth_security import AuthLoginAttempt

# 安全 hint / 审计 hash 前缀长度（不可逆，仅供运营粗略关联，绝非 email）。
HINT_LEN = 12

# 失败类结果（计入锁定 / 限流计数）。
_FAILED_RESULTS = ("failed", "locked", "rate_limited")
# 重置锚点：identifier 失败计数从最近一个锚点之后重新算。
# - success：用户成功登录；
# - unlocked：admin 手动解锁，同样作为 identifier lockout 的 reset anchor。
# 二者都**不**计入失败；unlocked 由 admin 运维写入，不绕过密码校验、不建会话。
_RESET_ANCHOR_RESULTS = ("success", "unlocked")

# 非 prod 空 secret 的稳定回退常量（仍单向 HMAC；prod 必须显式配置真实 secret）。
_FALLBACK_SECRET = "kap-dev-auth-attempt-hmac-fallback"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: datetime) -> datetime:
    """SQLite 读回的 naive datetime 视作 UTC（PostgreSQL 为 aware）。"""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _secret(settings: Settings | None = None) -> str:
    s = settings or get_settings()
    return (s.auth_attempt_hash_secret or "").strip() or _FALLBACK_SECRET


def _clamp(value: int | None, default: int) -> int:
    """阈值 / 窗口钳制：<1 或非法 → 回退安全默认（绝不导致无限放行）。"""
    try:
        v = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return max(1, default)
    return v if v >= 1 else max(1, default)


def normalize_login_identifier(email: str | None) -> str:
    """登录标识归一：去空白 + 小写（避免大小写 / 空白差异绕过锁定）。"""
    return (email or "").strip().lower()


def hash_login_identifier(value: str | None, *, purpose: str, settings: Settings | None = None) -> str:
    """对登录标识 / IP 做带 purpose 命名空间的 HMAC-SHA256（不可逆十六进制）。

    `purpose` 隔离 identifier 与 ip 两类哈希空间，避免交叉碰撞 / 反推。空值仍产生稳定 hash。
    """
    key = _secret(settings).encode("utf-8")
    msg = f"{purpose}:{value or ''}".encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def hash_prefix(value: str | None) -> str | None:
    """取 hash 安全前缀（审计 / hint 用）。None → None。"""
    return value[:HINT_LEN] if value else None


@dataclass(frozen=True)
class GuardResult:
    """登录守卫判定结果（仅安全字段，供审计 / 响应使用）。"""

    blocked: bool
    result: str | None  # locked / rate_limited
    reason_code: str | None  # identifier_locked / ip_rate_limited
    failed_count: int
    window_minutes: int
    lockout_minutes: int


async def _attempts_since(
    session: AsyncSession,
    *,
    column,
    value: str,
    since: datetime,
) -> list[AuthLoginAttempt]:
    rows = (
        await session.execute(
            select(AuthLoginAttempt)
            .where(column == value, AuthLoginAttempt.created_at >= since)
            .order_by(AuthLoginAttempt.created_at.desc())
        )
    ).scalars().all()
    return list(rows)


async def _last_reset_anchor_at(session: AsyncSession, identifier_hash: str) -> datetime | None:
    """最近一个 reset anchor（success 或 admin unlocked）的时间；无则 None。

    identifier 失败计数从该锚点**之后**重新算。
    """
    row = (
        await session.execute(
            select(AuthLoginAttempt.created_at)
            .where(
                AuthLoginAttempt.identifier_hash == identifier_hash,
                AuthLoginAttempt.result.in_(_RESET_ANCHOR_RESULTS),
            )
            .order_by(AuthLoginAttempt.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return _as_aware(row) if row is not None else None


async def check_login_guard(
    session: AsyncSession,
    *,
    identifier_hash: str,
    ip_hash: str | None,
    settings: Settings | None = None,
) -> GuardResult:
    """判定当前登录是否应被守卫直接拒绝（identifier 锁定优先于 IP 限流）。

    命中时调用方不做真实密码校验、写 locked/rate_limited attempt + 系统审计、返回统一 401。
    """
    s = settings or get_settings()
    now = _now()
    win = _clamp(s.auth_failed_window_minutes, 15)
    max_failed = _clamp(s.auth_max_failed_attempts, 5)
    lockout = _clamp(s.auth_lockout_minutes, 15)
    ip_win = _clamp(s.auth_ip_failed_window_minutes, 15)
    ip_max = _clamp(s.auth_ip_max_failed_attempts, 30)

    # ---- identifier 维度：自最近成功**之后**、窗口内的失败计数 ----
    # 取窗口内全部尝试，再用**严格** created_at > last_success 在内存过滤排除「成功及更早」。
    # 关键：用 `>`（而非 `>= effective_start`）—— DB 时间精度粗（如 SQLite）时，success 与其
    # 之前的 failed 可能落在同一时间戳；`>=` 会把这些旧 failed 误算进「成功之后」，导致
    # 「成功重置失败计数」不稳定（flaky）。严格 `>` 保证「成功及之前」的失败永不被重新计入。
    # 不用 (created_at == success AND id > success_id) 作 tie-break：id 是 uuid4，其序不代表
    # 插入序，反而会按概率错误地把旧 failed 算进来。代价仅是与 success **同一时间精度刻**内的
    # 极少数 post-success 失败暂不计入（保守、瞬时，下一刻即正常计入），不构成安全缺口。
    window_start = now - timedelta(minutes=win)
    last_anchor = await _last_reset_anchor_at(session, identifier_hash)
    id_attempts = await _attempts_since(
        session, column=AuthLoginAttempt.identifier_hash, value=identifier_hash, since=window_start
    )
    id_fails = [
        a
        for a in id_attempts
        if a.result in _FAILED_RESULTS
        and (last_anchor is None or _as_aware(a.created_at) > last_anchor)
    ]
    if len(id_fails) >= max_failed:
        last_fail_at = _as_aware(id_fails[0].created_at)  # desc 排序，[0] 为最近
        if now < last_fail_at + timedelta(minutes=lockout):
            return GuardResult(
                blocked=True, result="locked", reason_code="identifier_locked",
                failed_count=len(id_fails), window_minutes=win, lockout_minutes=lockout,
            )

    # ---- IP 维度：窗口内失败计数 ----
    if ip_hash:
        ip_start = now - timedelta(minutes=ip_win)
        ip_attempts = await _attempts_since(
            session, column=AuthLoginAttempt.ip_hash, value=ip_hash, since=ip_start
        )
        ip_fails = [a for a in ip_attempts if a.result in _FAILED_RESULTS]
        if len(ip_fails) >= ip_max:
            return GuardResult(
                blocked=True, result="rate_limited", reason_code="ip_rate_limited",
                failed_count=len(ip_fails), window_minutes=ip_win, lockout_minutes=lockout,
            )

    return GuardResult(
        blocked=False, result=None, reason_code=None,
        failed_count=len(id_fails), window_minutes=win, lockout_minutes=lockout,
    )


async def record_login_attempt(
    session: AsyncSession,
    *,
    identifier_hash: str,
    ip_hash: str | None,
    user_id: uuid.UUID | None,
    login_method: str,
    result: str,
    reason_code: str | None,
    trace_id: str | None,
) -> AuthLoginAttempt:
    """写一条登录尝试（只 add，不 commit；由调用方在同一事务提交）。"""
    attempt = AuthLoginAttempt(
        identifier_hash=identifier_hash,
        identifier_hint=hash_prefix(identifier_hash),
        user_id=user_id,
        ip_hash=ip_hash,
        login_method=login_method,
        result=result,
        reason_code=reason_code,
        trace_id=trace_id,
    )
    session.add(attempt)
    return attempt


async def record_login_success(
    session: AsyncSession,
    *,
    identifier_hash: str,
    ip_hash: str | None,
    user_id: uuid.UUID | None,
    login_method: str,
    trace_id: str | None,
) -> AuthLoginAttempt:
    """记录成功登录（后续 identifier 失败计数从此重置）。"""
    return await record_login_attempt(
        session, identifier_hash=identifier_hash, ip_hash=ip_hash, user_id=user_id,
        login_method=login_method, result="success", reason_code="success", trace_id=trace_id,
    )


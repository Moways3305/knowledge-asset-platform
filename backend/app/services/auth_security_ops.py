"""登录风控运维服务。

admin-only：近期登录风控聚合（counts + 最近事件安全视图）+ 手动解除 identifier 短时锁定。

安全红线：响应 / 审计**绝不**含 raw email / raw IP / 完整 identifier_hash·ip_hash /
password·hash·salt·digest / session token / token_hash / cookie / OAuth state。手动解锁只写
一条 `result="unlocked"` reset anchor + 安全审计，**不**绕过密码校验、不建会话、不改密码、
不重置 IP rate limit、不删历史 attempt。
"""

from __future__ import annotations

import re
import uuid
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.trace import generate_trace_id
from app.models.auth_security import AuthLoginAttempt
from app.models.identity import User
from app.schemas.auth_security import (
    AuthSecurityCounts,
    AuthSecurityEventItem,
    AuthSecurityOverviewResponse,
    AuthUnlockRequest,
    AuthUnlockResponse,
)
from app.schemas.enums import AuditAction, AuditLogType
from app.schemas.permission import CallerContext
from app.services import audit as audit_service
from app.services import auth_security

_DEFAULT_WINDOW = 60
_MAX_WINDOW = 7 * 24 * 60  # 7 天安全上限
_DEFAULT_LIMIT = 20
_MAX_LIMIT = 100
_RESULTS = ("failed", "success", "locked", "rate_limited", "unlocked")
# identifier_hash_prefix 解锁的最小前缀长度（防过宽匹配批量解锁）。
_MIN_PREFIX_LEN = 8
# 解锁匹配的 prefix 回看窗口（仅用于「唯一定位 identifier」，不影响锁定语义）。
_UNLOCK_LOOKBACK_MINUTES = 7 * 24 * 60


def _clamp(value: int | None, default: int, maximum: int) -> int:
    try:
        v = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(1, min(v, maximum))


def _denied(status: int, reason: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"denied_reason": reason, "message": message})


async def get_overview(
    session: AsyncSession,
    *,
    window_minutes: int | None,
    limit: int | None,
    result: str | None,
) -> AuthSecurityOverviewResponse:
    """近期登录风控聚合（admin-only，权限由调用方校验）。"""
    win = _clamp(window_minutes, _DEFAULT_WINDOW, _MAX_WINDOW)
    lim = _clamp(limit, _DEFAULT_LIMIT, _MAX_LIMIT)
    result_filter = result if result in _RESULTS else None
    window_start = auth_security._now() - timedelta(minutes=win)

    rows = list(
        (
            await session.execute(
                select(AuthLoginAttempt)
                .where(AuthLoginAttempt.created_at >= window_start)
                .order_by(AuthLoginAttempt.created_at.desc())
            )
        ).scalars().all()
    )

    counts = AuthSecurityCounts()
    identifiers: set[str] = set()
    ips: set[str] = set()
    for a in rows:
        if a.result == "failed":
            counts.failed += 1
        elif a.result == "locked":
            counts.locked += 1
        elif a.result == "rate_limited":
            counts.rate_limited += 1
        elif a.result == "success":
            counts.success += 1
        elif a.result == "unlocked":
            counts.unlocked += 1
        identifiers.add(a.identifier_hash)
        if a.ip_hash:
            ips.add(a.ip_hash)
    counts.unique_identifier_count = len(identifiers)
    counts.unique_ip_count = len(ips)

    events = [a for a in rows if result_filter is None or a.result == result_filter][:lim]
    # 已知用户安全显示名 / 状态（仅 user_id 非空）。
    user_ids = {a.user_id for a in events if a.user_id}
    name_status: dict[uuid.UUID, tuple[str, str]] = {}
    if user_ids:
        for uid, uname, ustatus in (
            await session.execute(
                select(User.id, User.name, User.status).where(User.id.in_(user_ids))
            )
        ).all():
            name_status[uid] = (uname, ustatus)

    recent = [
        AuthSecurityEventItem(
            attempt_id=a.id,
            identifier_hash_prefix=auth_security.hash_prefix(a.identifier_hash),
            ip_hash_prefix=auth_security.hash_prefix(a.ip_hash),
            user_id=a.user_id,
            user_name=(name_status.get(a.user_id, (None, None))[0] if a.user_id else None),
            user_status=(name_status.get(a.user_id, (None, None))[1] if a.user_id else None),
            login_method=a.login_method,
            result=a.result,
            reason_code=a.reason_code,
            created_at=auth_security._as_aware(a.created_at),
        )
        for a in events
    ]
    return AuthSecurityOverviewResponse(window_minutes=win, counts=counts, recent_events=recent)


async def _resolve_identifier_by_prefix(session: AsyncSession, prefix: str) -> str:
    """按**字面十六进制** identifier_hash 前缀唯一定位一个 identifier_hash（近期 attempt）。

    长度不足 → 422；非 hex（含 SQL LIKE 通配符 `%`/`_`、空白、`-` 等）→ 422；无匹配 →
    404；多匹配 → 409。identifier_hash 是 sha256 hex digest（0-9a-f），强制 hex 后传入
    `LIKE prefix + "%"` 不含任何用户可控通配符，按字面前缀匹配（不会把 `_`/`%` 当通配符）。"""
    prefix = (prefix or "").strip().lower()
    if len(prefix) < _MIN_PREFIX_LEN:
        raise _denied(422, "unlock_prefix_too_short", f"identifier 前缀至少 {_MIN_PREFIX_LEN} 位")
    if not re.fullmatch(r"[0-9a-f]+", prefix):
        raise _denied(422, "unlock_prefix_invalid", "identifier 前缀只能是十六进制字符（0-9a-f）")
    lookback = auth_security._now() - timedelta(minutes=_UNLOCK_LOOKBACK_MINUTES)
    matches = list(
        (
            await session.execute(
                select(AuthLoginAttempt.identifier_hash)
                .where(
                    AuthLoginAttempt.identifier_hash.like(prefix + "%"),
                    AuthLoginAttempt.created_at >= lookback,
                )
                .distinct()
            )
        ).scalars().all()
    )
    if not matches:
        raise _denied(404, "unlock_identifier_not_found", "未找到匹配的近期登录标识")
    if len(matches) > 1:
        raise _denied(409, "unlock_identifier_ambiguous", "前缀匹配到多个登录标识，请提供更长前缀")
    return matches[0]


async def unlock_identifier(
    session: AsyncSession,
    caller: CallerContext,
    *,
    body: AuthUnlockRequest,
    trace_id: str | None,
) -> AuthUnlockResponse:
    """手动解除 identifier 短时锁定（admin-only，权限由调用方校验）。

    写 `result="unlocked"` reset anchor（重置 identifier lockout）+ `auth.lockout_unlocked` 审计。
    不影响 IP rate limit（anchor 不带 ip_hash），不绕过密码校验、不建会话、不改密码。
    """
    if (body.user_id is None) == (not body.identifier_hash_prefix):
        # 两者都给或都不给 → 非法（必须二选一）。
        raise _denied(422, "unlock_input_invalid", "请提供 user_id 或 identifier_hash_prefix 之一")

    target_user_id: uuid.UUID | None = None
    if body.user_id is not None:
        user = (
            await session.execute(select(User).where(User.id == body.user_id))
        ).scalar_one_or_none()
        if user is None:
            raise _denied(404, "unlock_user_not_found", "用户不存在")
        target_user_id = user.id
        identifier = auth_security.normalize_login_identifier(user.email)
        identifier_hash = auth_security.hash_login_identifier(identifier, purpose="identifier")
    else:
        identifier_hash = await _resolve_identifier_by_prefix(session, body.identifier_hash_prefix)
        # 关联近期已知 user_id（若该 identifier 的近期 attempt 带 user_id），仅作安全元数据。
        target_user_id = (
            await session.execute(
                select(AuthLoginAttempt.user_id)
                .where(
                    AuthLoginAttempt.identifier_hash == identifier_hash,
                    AuthLoginAttempt.user_id.is_not(None),
                )
                .order_by(AuthLoginAttempt.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    # 统计被解除窗口内的失败类 attempt 数（安全数字，供审计/反馈）。
    win = auth_security._clamp(get_settings().auth_failed_window_minutes, 15)
    window_start = auth_security._now() - timedelta(minutes=win)
    matched = int(
        (
            await session.execute(
                select(func.count())
                .select_from(AuthLoginAttempt)
                .where(
                    AuthLoginAttempt.identifier_hash == identifier_hash,
                    AuthLoginAttempt.created_at >= window_start,
                    AuthLoginAttempt.result.in_(auth_security._FAILED_RESULTS),
                )
            )
        ).scalar() or 0
    )

    anchor = await auth_security.record_login_attempt(
        session,
        identifier_hash=identifier_hash,
        ip_hash=None,  # 不影响 IP rate limit
        user_id=target_user_id,
        login_method="manual_unlock",
        result="unlocked",
        reason_code="manual_unlock",
        trace_id=trace_id or generate_trace_id(),
    )
    await session.flush()  # 取 anchor.id 供审计

    prefix = auth_security.hash_prefix(identifier_hash)
    extra: dict = {
        "identifier_hash_prefix": prefix,
        "reset_attempt_id": str(anchor.id),
        "matched_attempt_count": matched,
        "window_minutes": win,
    }
    if target_user_id is not None:
        extra["target_user_id"] = str(target_user_id)
    if body.reason:
        extra["unlock_reason"] = body.reason[:200]
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.auth_lockout_unlocked.value,
        trace_id=trace_id or generate_trace_id(),
        target_type="auth_login_identifier",
        target_id=target_user_id,
        extra=extra,
    )
    await session.commit()

    return AuthUnlockResponse(
        ok=True,
        unlocked=True,
        user_id=target_user_id,
        identifier_hash_prefix=prefix,
        reset_at=auth_security._as_aware(anchor.created_at),
    )


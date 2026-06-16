"""平台会话撤销服务。

围绕 `user_sessions` 提供安全、可审计的会话撤销：账号安全变更（停用 / 改密）或 admin 强制
下线时，把目标用户的活动平台会话标记为已撤销（`revoked_at`）。**不物理删除**历史会话行，
不新增字段（复用既有 `revoked_at`）。

安全红线：本模块对外（响应 / 审计）**绝不**暴露 token / token_hash / cookie 值 / OAuth state /
ip / device_info / user-agent；`token_hash` 仅作 server-only 比对（标记当前会话 / 排除当前会话）。
会话对外只用安全 `session_id`（UserSession.id，非 token hash）+ 安全元数据。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_session import UserSession
from app.schemas.session_ops import UserSessionItem, UserSessionsResponse
from app.services.auth_session import _hash_token


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _is_active(s: UserSession, now: datetime) -> bool:
    """活动会话 = 未撤销且未过期。"""
    if s.revoked_at is not None:
        return False
    exp = _as_aware(s.expires_at)
    return exp is None or exp > now


async def _user_sessions(session: AsyncSession, user_id: uuid.UUID) -> list[UserSession]:
    return list(
        (
            await session.execute(
                select(UserSession)
                .where(UserSession.user_id == user_id)
                .order_by(UserSession.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


def current_token_hash(raw_session_token: str | None) -> str | None:
    """当前调用人会话 cookie 的 token_hash（server-only，用于标记 / 排除当前会话）。"""
    return _hash_token(raw_session_token) if raw_session_token else None


async def list_sessions(
    session: AsyncSession, user_id: uuid.UUID, *, current_hash: str | None
) -> UserSessionsResponse:
    """返回目标用户的安全会话元数据（无 token / hash / ip / device）。"""
    now = _now()
    rows = await _user_sessions(session, user_id)
    items = [
        UserSessionItem(
            session_id=s.id,
            login_method=s.login_method,
            created_at=s.created_at,
            last_seen_at=s.last_seen_at,
            expires_at=s.expires_at,
            revoked_at=s.revoked_at,
            active=_is_active(s, now),
            is_current_actor_session=(current_hash is not None and s.token_hash == current_hash),
        )
        for s in rows
    ]
    active_count = sum(1 for s in rows if _is_active(s, now))
    return UserSessionsResponse(user_id=user_id, active_count=active_count, sessions=items)


async def active_session_count(session: AsyncSession, user_id: uuid.UUID) -> int:
    now = _now()
    return sum(1 for s in await _user_sessions(session, user_id) if _is_active(s, now))


async def revoke_user_sessions(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    exclude_token_hash: str | None = None,
) -> tuple[int, datetime]:
    """撤销目标用户的活动会话（只 add/flush，不 commit；由调用方在同一事务提交）。

    `exclude_token_hash` 非空时保留该会话（用于「保留当前会话」）。返回 (撤销数, 撤销时刻)。
    标记 `revoked_at`，不删除行；已过期 / 已撤销的不重复处理。
    """
    now = _now()
    revoked = 0
    for s in await _user_sessions(session, user_id):
        if not _is_active(s, now):
            continue
        if exclude_token_hash is not None and s.token_hash == exclude_token_hash:
            continue
        s.revoked_at = now
        revoked += 1
    await session.flush()
    return revoked, now

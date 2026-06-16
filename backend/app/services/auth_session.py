"""会话身份服务。

提供登录 / 登出 / 当前会话解析与「会话 → 当前用户」的统一口径：

- 会话机制：服务端会话表 `user_sessions` + httpOnly cookie 中的不透明随机 token。
  服务端只存 sha256(token)，**明文 token 绝不进入任何 JSON 响应**，只经 Set-Cookie 下发。
- 当前用户解析优先级：先会话 cookie；无有效会话时，仅在 local/dev/test 回退到
  `X-Dev-User-Id`（或默认开发用户）；非开发环境且无有效会话 → 401。
- 登录凭证校验：密码登录校验 PBKDF2 后建会话；本地无凭证登录适配器（按 email 取
  active 用户建会话）仅在开发环境开放；企业微信 OAuth 经回调端点建会话（见 README）。
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_session import UserSession
from app.models.identity import User
from app.services.identity import (
    DEV_IDENTITY_ALLOWED_ENVS,
    load_user_with_roles,
    resolve_dev_user,
)

SESSION_COOKIE_NAME = "kap_session"
SESSION_TTL_HOURS = 12
# 本地无凭证登录适配器仅在开发环境开放（真实 OAuth 接入前的占位）。
LOGIN_ALLOWED_ENVS = DEV_IDENTITY_ALLOWED_ENVS


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: datetime) -> datetime:
    """SQLite 读回的 naive datetime 视作 UTC（PostgreSQL 为 aware）。"""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


async def create_session(
    session: AsyncSession,
    user: User,
    *,
    ip_address: str | None = None,
    device_info: str | None = None,
    login_method: str = "dev_local",
) -> str:
    """为 user 创建会话，返回**明文 token**（仅用于 Set-Cookie，不入 JSON）。

    只 add + flush，不 commit（由调用方在写登录审计后统一提交）。
    """
    raw_token = secrets.token_urlsafe(32)
    sess = UserSession(
        user_id=user.id,
        token_hash=_hash_token(raw_token),
        login_method=login_method,
        ip_address=ip_address,
        device_info=device_info,
        expires_at=_now() + timedelta(hours=SESSION_TTL_HOURS),
        last_seen_at=_now(),
    )
    session.add(sess)
    await session.flush()
    return raw_token


async def resolve_session_user(session: AsyncSession, raw_token: str | None) -> User | None:
    """按会话 cookie 明文 token 解析当前用户；无效 / 过期 / 撤销 → None。

    命中时更新 last_seen_at（尽力而为）。返回的 User 已预加载角色 / 成员关系。
    """
    if not raw_token:
        return None
    row = (
        await session.execute(
            select(UserSession).where(UserSession.token_hash == _hash_token(raw_token))
        )
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return None
    if _as_aware(row.expires_at) <= _now():
        return None
    row.last_seen_at = _now()
    user = await load_user_with_roles(session, user_id=row.user_id)
    if user is None or user.status != "active":
        return None
    return user


async def session_login_method(session: AsyncSession, raw_token: str | None) -> str | None:
    """读取 cookie 对应会话行的真实 `login_method`（password / dev_local / wecom_oauth）。

    纯读，供登出审计还原真实登录方式。**绝不**返回 / 暴露明文 token / token_hash / cookie 值。
    找不到会话行 → None（调用方据此不伪造 login_method）。
    """
    if not raw_token:
        return None
    row = (
        await session.execute(
            select(UserSession).where(UserSession.token_hash == _hash_token(raw_token))
        )
    ).scalar_one_or_none()
    return row.login_method if row is not None else None


async def revoke_session(session: AsyncSession, raw_token: str | None) -> bool:
    """撤销 cookie 对应会话（登出）。返回是否实际撤销了一条会话。"""
    if not raw_token:
        return False
    row = (
        await session.execute(
            select(UserSession).where(UserSession.token_hash == _hash_token(raw_token))
        )
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return False
    row.revoked_at = _now()
    return True


async def resolve_current_user(
    session: AsyncSession,
    *,
    app_env: str,
    session_token: str | None,
    dev_user_id: str | None,
) -> User:
    """当前用户统一解析（供 deps 与 /auth/me 共用）。

    1. 有效会话 cookie → 该用户（任何环境）。
    2. 否则，仅 local/dev/test 回退到 X-Dev-User-Id / 默认开发用户。
    3. 否则 → 401 not_authenticated。
    """
    user = await resolve_session_user(session, session_token)
    if user is not None:
        return user
    if app_env in DEV_IDENTITY_ALLOWED_ENVS:
        return await resolve_dev_user(session, app_env=app_env, dev_user_id=dev_user_id)
    raise HTTPException(status_code=401, detail="not_authenticated")


async def login_with_password(session: AsyncSession, *, email: str, password: str) -> User:
    """密码凭证登录（所有环境）：按 email 取用户并校验密码。

    统一失败语义（不区分原因，调用方一律 401 invalid_credentials）：用户不存在 / 非 active /
    未设置密码 / 密码错误。已知用户（exc.user_id 非空）由调用方写 login.failed；未知 email
    （user_id=None）不写可归属审计。对不存在用户也跑一次 PBKDF2 均衡时间侧信道。
    """
    from app.services.passwords import dummy_verify, verify_password

    user = await load_user_with_roles(session, email=email)
    if user is None:
        dummy_verify(password)
        raise _InvalidCredentials(user_id=None)
    # 校验密码（无 hash / 非 active 也统一失败；先校验密码再看状态，避免泄露"已设密码"信号）。
    if not verify_password(password, user.password_hash):
        raise _InvalidCredentials(user_id=user.id)
    if user.status != "active":
        raise _InvalidCredentials(user_id=user.id)
    return user


async def login_local(session: AsyncSession, *, app_env: str, email: str) -> User:
    """本地无凭证登录适配器（仅开发环境）：按 email 取 active 用户。

    - 非开发环境 → 403 auth_login_not_available（开发适配器仅限非生产环境）。
    - 用户不存在 / 非 active → 抛出，由调用方写 login.failed 审计后返回 401。

    注意：此开发适配器不校验密码 / OAuth 令牌；密码与企业微信 OAuth 凭证校验由各自的登录路径负责。
    """
    if app_env not in LOGIN_ALLOWED_ENVS:
        raise HTTPException(status_code=403, detail="auth_login_not_available")
    user = await load_user_with_roles(session, email=email)
    if user is None or user.status != "active":
        raise _InvalidCredentials(user_id=user.id if user is not None else None)
    return user


class _InvalidCredentials(Exception):
    """登录失败（用户不存在 / 非 active）。携带可选的已知 user_id 供审计归属。"""

    def __init__(self, user_id: uuid.UUID | None) -> None:
        self.user_id = user_id
        super().__init__("invalid_credentials")

"""API 依赖（dependencies）。

集中提供"当前调用人上下文"依赖。身份来源优先级：
1. 有效会话 cookie（`kap_session`）→ 会话用户（任何环境）。
2. 否则仅 local/dev/test 回退到开发态 mock identity（`X-Dev-User-Id` / 默认开发用户）。
3. 否则 → 401。

权限上下文（CallerContext）仍由 的 `build_caller_context` 构建，
本依赖只负责"当前用户从哪来"，不改任何业务权限语义。
"""

from __future__ import annotations

from fastapi import Cookie, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_db
from app.schemas.permission import CallerContext
from app.services.auth_session import SESSION_COOKIE_NAME, resolve_current_user
from app.services.permission import build_caller_context


async def get_caller_context(
    x_dev_user_id: str | None = Header(default=None, alias="X-Dev-User-Id"),
    kap_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    session: AsyncSession = Depends(get_db),
) -> CallerContext:
    """解析当前调用人并构建权限上下文。

    会话优先；无有效会话时仅开发环境回退到 mock identity。不实现真实 OAuth / JWT。
    """
    settings = get_settings()
    user = await resolve_current_user(
        session,
        app_env=settings.app_env,
        session_token=kap_session,
        dev_user_id=x_dev_user_id,
    )
    return build_caller_context(user)


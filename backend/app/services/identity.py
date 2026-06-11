"""身份解析服务。

包含两部分：
1. 开发态 mock identity 解析（resolve_dev_user）——仅限 local/dev/test，
   绝非正式鉴权，不实现 OAuth / JWT / Session。
2. 身份上下文组装（build_auth_me）——把 User + 其 active 公司角色 / 项目成员
   关系转换为 `/auth/me` 响应。
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.identity import ProjectMember, User
from app.schemas.auth import AuthMeOut, ProjectMembershipOut
from app.schemas.enums import (
    BUSINESS_COMPANY_ROLES,
    L5_DISCOVERY_ROLES,
    MemberStatus,
    RoleStatus,
)

# 仅在以下运行环境允许开发态 mock identity。生产环境必须改用真实鉴权。
DEV_IDENTITY_ALLOWED_ENVS: frozenset[str] = frozenset({"local", "dev", "test"})

# 默认开发用户邮箱（seed 中固定）。未携带 X-Dev-User-Id 时回退到该用户。
DEFAULT_DEV_USER_EMAIL = "consultant.a@dev.local"


async def load_user_with_roles(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    email: str | None = None,
    wecom_user_id: str | None = None,
) -> User | None:
    """按 id / email / wecom_user_id 加载用户，并预加载公司角色与项目成员（含项目）。

    供身份解析（dev 回退）、会话解析、本地登录与 WeCom OAuth 共用，确保
    build_caller_context / build_auth_me 能读取到 active 角色与成员关系。
    """
    stmt = select(User).options(
        selectinload(User.company_roles),
        selectinload(User.project_members).selectinload(ProjectMember.project),
    )
    if user_id is not None:
        stmt = stmt.where(User.id == user_id)
    elif wecom_user_id is not None:
        stmt = stmt.where(User.wecom_user_id == wecom_user_id)
    else:
        stmt = stmt.where(User.email == email)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# 向后兼容的私有别名（旧调用点）。
_load_user = load_user_with_roles


async def resolve_dev_user(
    session: AsyncSession,
    *,
    app_env: str,
    dev_user_id: str | None,
) -> User:
    """开发态当前用户解析。

    - 仅当 app_env ∈ {local, dev, test} 时允许；否则返回 403。
    - 携带 X-Dev-User-Id 时按该 id 解析；缺失时回退到默认开发用户。
    - 用户不存在返回 404。

    注意：这是开发态便捷机制，不是正式鉴权，不得用于生产环境。
    """
    if app_env not in DEV_IDENTITY_ALLOWED_ENVS:
        # 非开发环境禁止 mock identity，避免被误用为越权入口。
        raise HTTPException(status_code=403, detail="dev_identity_disabled")

    if dev_user_id:
        try:
            parsed = uuid.UUID(dev_user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid_dev_user_id") from exc
        user = await _load_user(session, user_id=parsed, email=None)
    else:
        # 未指定则回退到默认开发用户（按固定邮箱查找）。
        user = await _load_user(session, user_id=None, email=DEFAULT_DEV_USER_EMAIL)

    if user is None:
        raise HTTPException(status_code=404, detail="user_not_found")
    return user


def build_auth_me(user: User) -> AuthMeOut:
    """把 User 组装为 `/auth/me` 响应。

    - company_roles 只取 active 角色。
    - is_business_user：active 公司角色包含 boss / consulting_director / consultant。
    - can_discover_l5：active 公司角色包含 boss / consulting_director。
    - project_memberships 只取 active 成员关系，项目角色来自 project_members。
    - admin 即使在 active 公司角色中，也不会让 is_business_user / can_discover_l5
      变为 true（admin 不在业务/ L5 集合内）。
    """
    active_company_roles = [
        r.company_role for r in user.company_roles if r.status == RoleStatus.active.value
    ]

    is_business_user = any(role in BUSINESS_COMPANY_ROLES for role in active_company_roles)
    can_discover_l5 = any(role in L5_DISCOVERY_ROLES for role in active_company_roles)

    memberships = [
        ProjectMembershipOut(
            project_id=m.project_id,
            project_name=m.project.name,
            project_role=m.project_role,
            status=m.status,
        )
        for m in user.project_members
        if m.status == MemberStatus.active.value
    ]

    return AuthMeOut(
        user_id=user.id,
        name=user.name,
        email=user.email,
        status=user.status,
        company_roles=active_company_roles,
        is_business_user=is_business_user,
        can_discover_l5=can_discover_l5,
        project_memberships=memberships,
    )

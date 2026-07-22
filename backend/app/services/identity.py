"""身份解析服务。

包含两部分：
1. 开发态 mock identity 解析（resolve_dev_user）——仅限 local/dev/test，
   绝非正式鉴权，不实现 OAuth / JWT / Session。
2. 身份上下文组装（build_auth_me）——把 User + 其 active 公司角色 / 项目成员
   关系转换为 `/auth/me` 响应。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.identity import ProjectMember, User, UserCompanyRole
from app.schemas.auth import AuthMeOut, ProjectMembershipOut
from app.schemas.enums import (
    BUSINESS_COMPANY_ROLES,
    L5_DISCOVERY_ROLES,
    CompanyRole,
    MemberStatus,
    RoleStatus,
)
from app.services.wecom_client import WeComIdentity, WeComMemberStatus

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
    wecom_corp_id: str | None = None,
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
    elif wecom_user_id is not None and wecom_corp_id is not None:
        stmt = stmt.where(User.wecom_corp_id == wecom_corp_id, User.wecom_user_id == wecom_user_id)
    elif wecom_user_id is not None:
        stmt = stmt.where(User.wecom_user_id == wecom_user_id)
    else:
        stmt = stmt.where(User.email == email)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# 向后兼容的私有别名（旧调用点）。
_load_user = load_user_with_roles


@dataclass(frozen=True)
class WeComProvisionResult:
    user: User
    created: bool


def _clean_text(value: str | None, *, max_len: int) -> str | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    return cleaned[:max_len]


def _clean_email(value: str | None) -> str | None:
    cleaned = (value or "").strip().lower()
    if not cleaned or "@" not in cleaned:
        return None
    return cleaned[:255]


def _department_json(member: WeComMemberStatus) -> str | None:
    if not member.department_ids:
        return None
    return json.dumps(list(member.department_ids), ensure_ascii=False, separators=(",", ":"))


def _synthetic_wecom_email(user_id: uuid.UUID) -> str:
    return f"wecom-{user_id.hex}@wecom.local"


def _is_synthetic_wecom_email(email: str | None) -> bool:
    value = (email or "").strip().lower()
    return value.startswith("wecom-") and value.endswith("@wecom.local")


async def _email_available(
    session: AsyncSession, email: str, *, current_user_id: uuid.UUID | None = None
) -> bool:
    stmt = select(User.id).where(User.email == email)
    if current_user_id is not None:
        stmt = stmt.where(User.id != current_user_id)
    return (await session.execute(stmt)).scalar_one_or_none() is None


async def _load_wecom_user_for_binding(
    session: AsyncSession, *, corp_id: str, wecom_user_id: str
) -> User | None:
    user = await load_user_with_roles(session, wecom_corp_id=corp_id, wecom_user_id=wecom_user_id)
    if user is not None:
        return user
    legacy = await load_user_with_roles(session, wecom_user_id=wecom_user_id)
    if legacy is not None and legacy.wecom_corp_id is None:
        legacy.wecom_corp_id = corp_id
        await session.flush()
        return legacy
    return None


async def _sync_wecom_profile(
    session: AsyncSession, user: User, *, corp_id: str, member: WeComMemberStatus
) -> None:
    """同步安全展示字段。空企微邮箱不会覆盖平台已有邮箱。"""
    from app.db.utils import utc_now

    user.wecom_corp_id = corp_id
    user.wecom_user_id = member.wecom_user_id
    synced_name = _clean_text(member.name, max_len=100)
    if synced_name:
        user.wecom_name = synced_name
        user.name = synced_name
    synced_email = _clean_email(member.email)
    if synced_email:
        user.wecom_email = synced_email
        if user.email != synced_email and (
            _is_synthetic_wecom_email(user.email)
            or await _email_available(session, synced_email, current_user_id=user.id)
        ):
            user.email = synced_email
    avatar = _clean_text(member.avatar, max_len=500)
    if avatar:
        user.wecom_avatar = avatar
    departments = _department_json(member)
    if departments:
        user.wecom_department_ids = departments
    user.wecom_synced_at = utc_now()


async def resolve_or_provision_wecom_user(
    session: AsyncSession,
    *,
    corp_id: str,
    identity: WeComIdentity,
    member: WeComMemberStatus,
) -> WeComProvisionResult:
    """按服务端可信企微身份解析或自动创建平台用户。

    唯一身份只来自 `corp_id + userid`；姓名/邮箱只做展示同步，不能作为登录归并键。
    新用户默认 active + consultant，不授予 admin / boss / director / 项目成员等高权限。
    """
    user = await _load_wecom_user_for_binding(
        session, corp_id=corp_id, wecom_user_id=identity.wecom_user_id
    )
    if user is not None:
        await _sync_wecom_profile(session, user, corp_id=corp_id, member=member)
        await session.flush()
        return WeComProvisionResult(user=user, created=False)

    user_id = uuid.uuid4()
    preferred_email = _clean_email(member.email)
    email = (
        preferred_email
        if preferred_email and await _email_available(session, preferred_email)
        else _synthetic_wecom_email(user_id)
    )
    name = _clean_text(member.name, max_len=100) or f"企微用户 {user_id.hex[:8]}"
    user = User(
        id=user_id,
        name=name,
        email=email,
        status="active",
        wecom_corp_id=corp_id,
        wecom_user_id=identity.wecom_user_id,
    )
    user.company_roles.append(
        UserCompanyRole(company_role=CompanyRole.consultant.value, status=RoleStatus.active.value)
    )
    session.add(user)
    await session.flush()
    await _sync_wecom_profile(session, user, corp_id=corp_id, member=member)
    await session.flush()
    return WeComProvisionResult(user=user, created=True)


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


def build_auth_me(user: User, *, active_company_role: str | None = None) -> AuthMeOut:
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

    from app.services.work_identity import default_active_role

    selected_role = active_company_role or default_active_role(user)
    if selected_role not in active_company_roles:
        selected_role = None
    is_business_user = selected_role in BUSINESS_COMPANY_ROLES
    can_discover_l5 = selected_role in L5_DISCOVERY_ROLES

    memberships = [
        ProjectMembershipOut(
            project_id=m.project_id,
            project_name=m.project.name,
            project_role=m.project_role,
            status=m.status,
        )
        for m in user.project_members
        if m.status == MemberStatus.active.value and selected_role in BUSINESS_COMPANY_ROLES
    ]

    return AuthMeOut(
        user_id=user.id,
        name=user.name,
        email=user.email,
        status=user.status,
        company_roles=active_company_roles,
        active_company_role=selected_role,
        is_business_user=is_business_user,
        can_discover_l5=can_discover_l5,
        project_memberships=memberships,
    )

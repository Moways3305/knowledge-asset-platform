"""人员 / 公司角色 / 项目成员关系治理服务。

复用既有表 `users` / `user_company_roles` / `projects` / `project_members` /
`user_sessions`（仅安全聚合最近会话时间）。不新增 demo-only 字段、不物理删除关系。

权限边界（后端权威）：
- 读人员列表 / 详情：admin / boss / 咨询总监；consultant → 403。
- 管理公司角色：boss / 咨询总监 / admin 可管理业务角色（boss/consulting_director/consultant）；
  **仅 admin** 可分配 / 移除 `admin` 角色；consultant 无权。不允许停掉最后一个 active admin。
- 管理项目成员关系：boss / 咨询总监 / admin；consultant 无权。
- admin 是系统身份：可做人员/角色系统维护，但**不因此获得任何业务原文权限**（原文权限只来自
  目标用户自己的 active 项目成员关系，由权限服务读取，与本服务的写动作无关）。

安全：响应 / 审计绝不含 token / token_hash / OAuth code·state / ip / device_info /
wecom_user_id 明文 / 业务原文 / provider 内部标识。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.auth_session import UserSession
from app.models.identity import Project, ProjectMember, User, UserCompanyRole
from app.schemas.enums import (
    AuditAction,
    AuditLogType,
    CompanyRole,
    RoleStatus,
    UserStatus,
)
from app.schemas.people import (
    CompanyRoleOut,
    CompanyRoleUpdateRequest,
    PeopleListResponse,
    PersonOut,
    PersonProjectMembershipOut,
    ProjectMembershipCreateRequest,
    ProjectMembershipPatchRequest,
    SetPasswordRequest,
    SetPasswordResponse,
    UserStatusUpdateRequest,
)
from app.schemas.permission import CallerContext
from app.services import audit as audit_service
from app.services import passwords as password_service
from app.services import session_revocation

_MAX_LIMIT = 100


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"denied_reason": reason, "message": message})


def _is_admin(caller: CallerContext) -> bool:
    return CompanyRole.admin.value in caller.active_company_roles


def _is_governance(caller: CallerContext) -> bool:
    # 业务治理角色 = boss / consulting_director（与可发现 L5 一致）。
    return caller.can_discover_l5


def _require_read(caller: CallerContext) -> None:
    """读人员：admin 或治理角色（boss/咨询总监）。consultant / 其他 → 403。"""
    if not (_is_admin(caller) or _is_governance(caller)):
        raise _denied(403, "people_admin_forbidden", "无人员治理查看权限")


def _require_manage_company_role(caller: CallerContext, target_role: str) -> None:
    """管理公司角色：admin 角色仅 admin 可管；业务角色 admin/boss/咨询总监可管。"""
    if target_role == CompanyRole.admin.value:
        if not _is_admin(caller):
            raise _denied(403, "admin_role_requires_admin", "仅 admin 可分配 / 移除 admin 角色")
        return
    if not (_is_admin(caller) or _is_governance(caller)):
        raise _denied(403, "people_admin_forbidden", "无管理公司角色的权限")


def _require_manage_membership(caller: CallerContext) -> None:
    """管理项目成员关系：admin / boss / 咨询总监。consultant 无权。"""
    if not (_is_admin(caller) or _is_governance(caller)):
        raise _denied(403, "people_admin_forbidden", "无管理项目成员关系的权限")


def _as_aware(dt: datetime | None) -> datetime | None:
    """把可能为 naive（SQLite）的时间归一化为 aware UTC，便于比较。"""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


async def _recent_session_map(
    session: AsyncSession, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, datetime]:
    """每个用户的最近会话时间 = max(last_seen_at, created_at)。

    只读 user_id / last_seen_at / created_at 三列——**绝不**读 token_hash / ip / device_info。
    """
    if not user_ids:
        return {}
    rows = (
        await session.execute(
            select(UserSession.user_id, UserSession.last_seen_at, UserSession.created_at)
            .where(UserSession.user_id.in_(user_ids))
        )
    ).all()
    out: dict[uuid.UUID, datetime] = {}
    for uid, last_seen, created in rows:
        candidates = [c for c in (_as_aware(last_seen), _as_aware(created)) if c is not None]
        if not candidates:
            continue
        latest = max(candidates)
        if uid not in out or latest > out[uid]:
            out[uid] = latest
    return out


def _person_out(
    user: User, recent_session_at: datetime | None, active_session_count: int = 0
) -> PersonOut:
    return PersonOut(
        user_id=user.id,
        name=user.name,
        email=user.email,
        phone=user.phone,
        wecom_bound=user.wecom_user_id is not None,
        status=user.status,
        created_at=user.created_at,
        updated_at=user.updated_at,
        company_roles=[
            CompanyRoleOut(role_id=r.id, company_role=r.company_role, status=r.status)
            for r in user.company_roles
        ],
        project_memberships=[
            PersonProjectMembershipOut(
                membership_id=m.id,
                project_id=m.project_id,
                project_name=m.project.name,
                project_role=m.project_role,
                status=m.status,
                joined_at=m.joined_at,
            )
            for m in user.project_members
        ],
        recent_session_at=recent_session_at,
        active_session_count=active_session_count,
        password_set=bool(user.password_hash),
        password_set_at=user.password_set_at,
    )


def _with_relations(stmt):
    return stmt.options(
        selectinload(User.company_roles),
        selectinload(User.project_members).selectinload(ProjectMember.project),
    )


async def list_people(
    session: AsyncSession,
    caller: CallerContext,
    *,
    role: str | None = None,
    status: str | None = None,
    q: str | None = None,
    project_id: uuid.UUID | None = None,
    limit: int = _MAX_LIMIT,
    offset: int = 0,
) -> PeopleListResponse:
    _require_read(caller)

    limit = max(1, min(limit, _MAX_LIMIT))
    offset = max(0, offset)

    conditions = []
    if status:
        conditions.append(User.status == status)
    if q:
        like = f"%{q}%"
        conditions.append(or_(User.name.ilike(like), User.email.ilike(like)))
    if role:
        conditions.append(
            User.id.in_(
                select(UserCompanyRole.user_id).where(
                    UserCompanyRole.company_role == role,
                    UserCompanyRole.status == RoleStatus.active.value,
                )
            )
        )
    if project_id is not None:
        conditions.append(
            User.id.in_(
                select(ProjectMember.user_id).where(
                    ProjectMember.project_id == project_id,
                    ProjectMember.status == "active",
                )
            )
        )

    total = (
        await session.execute(select(func.count()).select_from(User).where(*conditions))
    ).scalar_one()

    users = list(
        (
            await session.execute(
                _with_relations(select(User).where(*conditions))
                .order_by(User.created_at)
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    recent = await _recent_session_map(session, [u.id for u in users])
    return PeopleListResponse(
        items=[_person_out(u, recent.get(u.id)) for u in users],
        total=int(total),
    )


async def _load_person(session: AsyncSession, user_id: uuid.UUID) -> User:
    user: User | None = (
        await session.execute(_with_relations(select(User).where(User.id == user_id)))
    ).scalar_one_or_none()
    if user is None:
        raise _denied(404, "user_not_found", "用户不存在")
    return user


async def get_person(session: AsyncSession, caller: CallerContext, user_id: uuid.UUID) -> PersonOut:
    _require_read(caller)
    user = await _load_person(session, user_id)
    recent = await _recent_session_map(session, [user.id])
    active = await session_revocation.active_session_count(session, user.id)
    return _person_out(user, recent.get(user.id), active)


async def set_company_role(
    session: AsyncSession,
    caller: CallerContext,
    user_id: uuid.UUID,
    req: CompanyRoleUpdateRequest,
    trace_id: str,
) -> PersonOut:
    """设置 / 启停公司角色（upsert by user_id + company_role）。"""
    target_role = req.company_role.value
    new_status = req.status.value
    _require_manage_company_role(caller, target_role)

    user = await _load_person(session, user_id)
    existing = next((r for r in user.company_roles if r.company_role == target_role), None)
    old_status = existing.status if existing else None

    # 不允许停掉最后一个**可用** admin（避免系统失去人员治理能力）。
    # 可用 admin 必须三者皆满足：users.status=active + company_role=admin + role.status=active。
    # 只数 active admin role 行是不够的——inactive 用户挂着 active admin role 属脏数据，
    # 不能被当作可用 admin（否则会放行停用最后一个真正可登录的 admin）。
    if target_role == CompanyRole.admin.value and new_status != RoleStatus.active.value:
        user_is_active = user.status == UserStatus.active.value
        currently_active = (
            user_is_active
            and existing is not None
            and existing.status == RoleStatus.active.value
        )
        if currently_active:
            usable_admins = (
                await session.execute(
                    select(func.count())
                    .select_from(UserCompanyRole)
                    .join(User, User.id == UserCompanyRole.user_id)
                    .where(
                        UserCompanyRole.company_role == CompanyRole.admin.value,
                        UserCompanyRole.status == RoleStatus.active.value,
                        User.status == UserStatus.active.value,
                    )
                )
            ).scalar_one()
            if int(usable_admins) <= 1:
                raise _denied(409, "last_active_admin_protected", "不能停用最后一个可用 admin")

    if existing is None:
        role_row = UserCompanyRole(company_role=target_role, status=new_status)
        # 通过关系集合追加，保证同一 session 内重读（get_person）能看到新行。
        user.company_roles.append(role_row)
        await session.flush()
    else:
        role_row = existing
        role_row.status = new_status
        await session.flush()

    await audit_service.record_event(
        session, caller=caller, log_type=AuditLogType.operation,
        action=AuditAction.config_people_company_role_updated.value, trace_id=trace_id,
        target_type="user_company_role", target_id=role_row.id,
        extra={
            "target_user_id": str(user.id),
            "company_role": target_role,
            "old_status": old_status,
            "new_status": new_status,
        },
    )
    await session.commit()
    return await get_person(session, caller, user_id)


async def list_project_memberships(
    session: AsyncSession, caller: CallerContext, user_id: uuid.UUID
) -> list[PersonProjectMembershipOut]:
    """该用户所有项目成员关系（含 inactive，便于治理审计）。"""
    _require_read(caller)
    user = await _load_person(session, user_id)
    return [
        PersonProjectMembershipOut(
            membership_id=m.id,
            project_id=m.project_id,
            project_name=m.project.name,
            project_role=m.project_role,
            status=m.status,
            joined_at=m.joined_at,
        )
        for m in user.project_members
    ]


async def upsert_project_membership(
    session: AsyncSession,
    caller: CallerContext,
    user_id: uuid.UUID,
    req: ProjectMembershipCreateRequest,
    trace_id: str,
) -> PersonProjectMembershipOut:
    """新增 / 恢复项目成员关系（upsert by user_id + project_id）。"""
    _require_manage_membership(caller)
    user = await _load_person(session, user_id)

    project = (
        await session.execute(select(Project).where(Project.id == req.project_id))
    ).scalar_one_or_none()
    if project is None:
        raise _denied(404, "project_not_found", "目标项目不存在")

    new_role = req.project_role.value
    new_status = req.status.value
    existing = next((m for m in user.project_members if m.project_id == req.project_id), None)
    old_status = existing.status if existing else None

    if existing is None:
        member = ProjectMember(
            project_id=req.project_id, project_role=new_role, status=new_status,
        )
        # 通过关系集合追加，保证同一 session 内重读能看到新成员行。
        user.project_members.append(member)
        await session.flush()
    else:
        member = existing
        member.project_role = new_role
        member.status = new_status
        await session.flush()

    await audit_service.record_event(
        session, caller=caller, log_type=AuditLogType.operation,
        action=AuditAction.config_people_project_membership_updated.value, trace_id=trace_id,
        target_type="project_member", target_id=member.id,
        extra={
            "target_user_id": str(user.id),
            "project_id": str(req.project_id),
            "project_role": new_role,
            "old_status": old_status,
            "new_status": new_status,
        },
        project_id=req.project_id,
    )
    await session.commit()
    return PersonProjectMembershipOut(
        membership_id=member.id, project_id=member.project_id, project_name=project.name,
        project_role=member.project_role, status=member.status, joined_at=member.joined_at,
    )


async def patch_project_membership(
    session: AsyncSession,
    caller: CallerContext,
    user_id: uuid.UUID,
    membership_id: uuid.UUID,
    req: ProjectMembershipPatchRequest,
    trace_id: str,
) -> PersonProjectMembershipOut:
    """更新项目成员关系角色 / 状态（禁用用 status=inactive，不物理删除）。"""
    _require_manage_membership(caller)
    user = await _load_person(session, user_id)

    member = next((m for m in user.project_members if m.id == membership_id), None)
    if member is None:
        # membership 不属于该 user：404，不泄露其它用户关系细节。
        raise _denied(404, "membership_not_found", "项目成员关系不存在")

    if req.project_role is None and req.status is None:
        raise _denied(422, "no_membership_change", "至少需提供 project_role 或 status")

    old_role, old_status = member.project_role, member.status
    if req.project_role is not None:
        member.project_role = req.project_role.value
    if req.status is not None:
        member.status = req.status.value
    await session.flush()

    await audit_service.record_event(
        session, caller=caller, log_type=AuditLogType.operation,
        action=AuditAction.config_people_project_membership_updated.value, trace_id=trace_id,
        target_type="project_member", target_id=member.id,
        extra={
            "target_user_id": str(user.id),
            "project_id": str(member.project_id),
            "project_role": member.project_role,
            "old_role": old_role,
            "old_status": old_status,
            "new_status": member.status,
        },
        project_id=member.project_id,
    )
    await session.commit()
    project_name = member.project.name
    return PersonProjectMembershipOut(
        membership_id=member.id, project_id=member.project_id, project_name=project_name,
        project_role=member.project_role, status=member.status, joined_at=member.joined_at,
    )


# ---------------------------------------------------------------------------
# 密码设置 / 重置
# ---------------------------------------------------------------------------
def _require_admin_only(caller: CallerContext) -> None:
    """仅 active 系统 admin 可设置 / 重置密码（boss / 咨询总监 / consultant 一律不可）。"""
    if not (caller.is_active and _is_admin(caller)):
        raise _denied(403, "password_set_admin_required", "仅系统管理员可设置 / 重置用户密码")


async def set_password(
    session: AsyncSession, caller: CallerContext, user_id: uuid.UUID,
    req: SetPasswordRequest, trace_id: str,
) -> SetPasswordResponse:
    """管理员为用户设置 / 重置密码。

    仅 admin；不存在用户 → 404；弱密码 → 422。允许给 inactive 用户设密码（admin 维护），
    但 inactive 用户登录仍失败（`login_with_password` 校验 status）。审计只记安全元数据，
    **绝不**含 password / hash / salt / digest。
    """
    _require_admin_only(caller)
    user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise _denied(404, "user_not_found", "用户不存在")
    err = password_service.validate_password_strength(req.password)
    if err is not None:
        raise _denied(422, "weak_password", err)

    user.password_hash = password_service.hash_password(req.password)
    user.password_set_at = datetime.now(timezone.utc)
    await audit_service.record_event(
        session, caller=caller, log_type=AuditLogType.operation,
        action=AuditAction.auth_password_set.value, trace_id=trace_id,
        target_type="user", target_id=user.id,
        extra={
            "password_set": True,
            "target_user_status": user.status,
            "actor_is_admin": True,
        },
    )
    # 改密后撤销目标用户全部活动平台会话（含其本人若 admin 改自己密码——强制重登）。
    revoked, _ = await session_revocation.revoke_user_sessions(session, user.id)
    if revoked:
        await audit_service.record_event(
            session, caller=caller, log_type=AuditLogType.operation,
            action=AuditAction.auth_sessions_revoked.value, trace_id=trace_id,
            target_type="user", target_id=user.id,
            extra={"target_user_id": str(user.id), "revoked_count": revoked,
                   "trigger": "password_reset", "preserved_current_session": False},
        )
    await session.commit()
    return SetPasswordResponse(
        user_id=user.id, password_set=True, password_set_at=user.password_set_at
    )


async def set_user_status(
    session: AsyncSession, caller: CallerContext, user_id: uuid.UUID,
    req: UserStatusUpdateRequest, trace_id: str,
) -> PersonOut:
    """启用 / 停用用户。active→inactive 联动撤销其全部活动平台会话。

    fail-closed：不能停用自己（避免 admin 自锁）；不能停用最后一个可用 admin。停用后该用户
    立即下线（会话撤销）且登录校验 status 失败。审计只记安全元数据。"""
    _require_admin_only(caller)
    new_status = req.status.value
    user = await _load_person(session, user_id)  # 预加载 company_roles（避免异步惰性加载）
    if new_status == UserStatus.inactive.value and user.id == caller.user_id:
        raise _denied(409, "cannot_deactivate_self", "不能停用当前登录的自己")

    old_status = user.status
    deactivating = (
        old_status == UserStatus.active.value and new_status == UserStatus.inactive.value
    )
    # 不允许停用最后一个可用 admin（与公司角色停用同口径）。
    if deactivating:
        is_admin_user = any(
            r.company_role == CompanyRole.admin.value and r.status == RoleStatus.active.value
            for r in user.company_roles
        )
        if is_admin_user:
            usable_admins = (
                await session.execute(
                    select(func.count())
                    .select_from(UserCompanyRole)
                    .join(User, User.id == UserCompanyRole.user_id)
                    .where(
                        UserCompanyRole.company_role == CompanyRole.admin.value,
                        UserCompanyRole.status == RoleStatus.active.value,
                        User.status == UserStatus.active.value,
                    )
                )
            ).scalar_one()
            if int(usable_admins) <= 1:
                raise _denied(409, "last_active_admin_protected", "不能停用最后一个可用 admin")

    user.status = new_status
    await session.flush()
    await audit_service.record_event(
        session, caller=caller, log_type=AuditLogType.operation,
        action=AuditAction.config_people_status_updated.value, trace_id=trace_id,
        target_type="user", target_id=user.id,
        extra={"target_user_id": str(user.id), "old_status": old_status, "new_status": new_status},
    )
    # 停用 → 撤销目标用户全部活动平台会话（强制下线）。
    if deactivating:
        revoked, _ = await session_revocation.revoke_user_sessions(session, user.id)
        if revoked:
            await audit_service.record_event(
                session, caller=caller, log_type=AuditLogType.operation,
                action=AuditAction.auth_sessions_revoked.value, trace_id=trace_id,
                target_type="user", target_id=user.id,
                extra={"target_user_id": str(user.id), "revoked_count": revoked,
                       "trigger": "user_deactivated", "preserved_current_session": False},
            )
    await session.commit()
    return await get_person(session, caller, user_id)


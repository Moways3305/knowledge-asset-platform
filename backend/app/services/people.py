"""人员 / 公司角色 / 项目成员关系治理服务。

复用既有表 `users` / `user_company_roles` / `projects` / `project_members` /
`user_sessions`（仅安全聚合最近会话时间）。不新增 demo-only 字段；项目成员关系
默认走 status=inactive 软停用，`remove_project_membership` 提供显式物理删除入口。

权限边界（后端权威）：
- 读人员列表 / 详情：boss / 咨询总监；admin / consultant → 403。
- 管理业务公司角色：boss 可管理 boss / consulting_director / consultant；咨询总监仅可管理
  consulting_director / consultant；咨询总监不可修改总经理。技术 `admin` 角色无 HTTP 管理路径。
- 总经理 / 咨询总监任命项目经理；项目经理独立管理本项目辅导老师与顾问。
- 不允许停掉最后一个可用 admin 或最后一个可用总经理。
- admin 是系统审计/运维身份，不可读取或修改本服务中的人员治理数据。

安全：响应 / 审计绝不含 token / token_hash / OAuth code·state / ip / device_info /
wecom_user_id 明文 / 业务原文 / provider 内部标识。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.auth_session import UserSession
from app.models.identity import Project, ProjectMember, User, UserCompanyRole
from app.schemas.enums import (
    AuditAction,
    AuditLogType,
    CompanyRole,
    MemberStatus,
    ProjectRole,
    ProjectStatus,
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
from app.services import governance_policy, session_revocation
from app.services import passwords as password_service

_MAX_LIMIT = 100


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"denied_reason": reason, "message": message}
    )


def _is_admin(caller: CallerContext) -> bool:
    return governance_policy.is_admin(caller)


def _is_governance(caller: CallerContext) -> bool:
    return governance_policy.is_governance(caller)


def _require_read(caller: CallerContext) -> None:
    """人员治理数据仅 boss / 咨询总监可读。"""
    if not _is_governance(caller):
        reason = (
            "admin_business_permission_denied" if _is_admin(caller) else "people_admin_forbidden"
        )
        raise _denied(403, reason, "无人员治理查看权限")


async def _record_governance_denied(
    session: AsyncSession,
    caller: CallerContext,
    *,
    trace_id: str,
    reason: str,
    attempted: str,
    target_role: str | None = None,
) -> None:
    extra = {"denied_reason": reason, "attempted": attempted}
    if target_role is not None:
        extra["company_role"] = target_role
    await audit_service.record_denied(
        session,
        caller=caller,
        log_type=AuditLogType.exception,
        action=AuditAction.config_people_company_role_updated.value,
        trace_id=trace_id,
        target_type="people_governance",
        extra=extra,
    )


async def _require_manage_company_role(
    session: AsyncSession, caller: CallerContext, target_role: str, trace_id: str
) -> None:
    """可信 CallerContext 授权矩阵；拒绝路径先写安全审计。"""
    if governance_policy.can_manage_company_role(caller, target_role):
        return
    if target_role == CompanyRole.admin.value:
        reason = "admin_role_browser_management_forbidden"
    else:
        reason = (
            "admin_business_permission_denied"
            if _is_admin(caller)
            else "company_role_management_forbidden"
        )
    await _record_governance_denied(
        session,
        caller,
        trace_id=trace_id,
        reason=reason,
        attempted="people.company_role.update",
        target_role=target_role,
    )
    message = (
        "技术管理员角色不提供网页管理入口"
        if target_role == CompanyRole.admin.value
        else "当前身份不可管理该业务角色"
    )
    raise _denied(403, reason, message)


async def _require_manage_membership(
    session: AsyncSession,
    caller: CallerContext,
    trace_id: str,
    *,
    project_id: uuid.UUID,
    current_role: str | None,
    requested_role: str,
) -> None:
    """公司治理任命项目经理；项目经理管理本项目辅导老师与顾问。"""
    if governance_policy.can_assign_project_role(
        caller,
        project_id,
        current_role=current_role,
        requested_role=requested_role,
    ):
        return
    elif requested_role == ProjectRole.project_manager.value and not _is_governance(caller):
        reason = "project_manager_appointment_requires_governance"
    else:
        reason = (
            "admin_business_permission_denied"
            if _is_admin(caller)
            else "project_membership_management_forbidden"
        )
    await _record_governance_denied(
        session,
        caller,
        trace_id=trace_id,
        reason=reason,
        attempted="people.project_membership.update",
    )
    raise _denied(403, reason, "当前身份不可管理该项目成员关系")


async def _require_governance_account_management(
    session: AsyncSession,
    caller: CallerContext,
    *,
    trace_id: str,
    attempted: str,
    action: str,
) -> None:
    if not _is_governance(caller):
        reason = (
            "admin_business_permission_denied"
            if _is_admin(caller)
            else "people_governance_required"
        )
        await audit_service.record_denied(
            session,
            caller=caller,
            log_type=AuditLogType.exception,
            action=action,
            trace_id=trace_id,
            target_type="people_governance",
            extra={"denied_reason": reason, "attempted": attempted},
        )
        raise _denied(403, reason, "仅总经理或咨询总监可管理人员账号")


def _director_cannot_manage_boss(caller: CallerContext, user: User) -> None:
    if CompanyRole.consulting_director.value in caller.active_company_roles and any(
        role.company_role == CompanyRole.boss.value and role.status == RoleStatus.active.value
        for role in user.company_roles
    ):
        raise _denied(
            403,
            "consulting_director_cannot_manage_general_manager",
            "咨询总监不可修改总经理",
        )


async def _usable_role_count(session: AsyncSession, role: str) -> int:
    """锁定并统计可登录的 active 角色持有人，供最后 admin/总经理保护。"""
    rows = (
        (
            await session.execute(
                select(UserCompanyRole.id)
                .join(User, User.id == UserCompanyRole.user_id)
                .where(
                    UserCompanyRole.company_role == role,
                    UserCompanyRole.status == RoleStatus.active.value,
                    User.status == UserStatus.active.value,
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    return len(rows)


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
            select(UserSession.user_id, UserSession.last_seen_at, UserSession.created_at).where(
                UserSession.user_id.in_(user_ids)
            )
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
    await _require_manage_company_role(session, caller, target_role, trace_id)
    user = await _load_person(session, user_id)
    if CompanyRole.consulting_director.value in caller.active_company_roles and any(
        role.company_role == CompanyRole.boss.value and role.status == RoleStatus.active.value
        for role in user.company_roles
    ):
        await _record_governance_denied(
            session,
            caller,
            trace_id=trace_id,
            reason="consulting_director_cannot_manage_general_manager",
            attempted="people.company_role.update",
            target_role=target_role,
        )
        raise _denied(
            403, "consulting_director_cannot_manage_general_manager", "咨询总监不可修改总经理"
        )
    existing = next((r for r in user.company_roles if r.company_role == target_role), None)
    old_status = existing.status if existing else None

    # 不允许停掉最后一个可用 admin / 总经理。可用必须同时满足 active 用户与 active 角色。
    if (
        target_role
        in {
            CompanyRole.admin.value,
            CompanyRole.boss.value,
        }
        and new_status != RoleStatus.active.value
    ):
        user_is_active = user.status == UserStatus.active.value
        currently_active = (
            user_is_active and existing is not None and existing.status == RoleStatus.active.value
        )
        if currently_active:
            usable = await _usable_role_count(session, target_role)
            if usable <= 1:
                reason = (
                    "last_active_admin_protected"
                    if target_role == CompanyRole.admin.value
                    else "last_active_boss_protected"
                )
                label = "admin" if target_role == CompanyRole.admin.value else "总经理"
                raise _denied(409, reason, f"不能停用最后一个可用 {label}")

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
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.config_people_company_role_updated.value,
        trace_id=trace_id,
        target_type="user_company_role",
        target_id=role_row.id,
        extra={
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
    if _is_admin(caller):
        await _require_manage_membership(
            session,
            caller,
            trace_id,
            project_id=req.project_id,
            current_role=None,
            requested_role=req.project_role.value,
        )
    user = await _load_person(session, user_id)
    if req.status.value == "active" and user.status != UserStatus.active.value:
        raise _denied(422, "active_project_member_required", "仅 active 用户可加入项目")

    project = (
        await session.execute(select(Project).where(Project.id == req.project_id))
    ).scalar_one_or_none()
    if project is None:
        raise _denied(404, "project_not_found", "目标项目不存在")

    new_role = req.project_role.value
    new_status = req.status.value
    existing = next((m for m in user.project_members if m.project_id == req.project_id), None)
    old_status = existing.status if existing else None
    await _require_manage_membership(
        session,
        caller,
        trace_id,
        project_id=req.project_id,
        current_role=existing.project_role if existing else None,
        requested_role=new_role,
    )

    if existing is None:
        member = ProjectMember(
            project_id=req.project_id,
            project_role=new_role,
            status=new_status,
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
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.config_people_project_membership_updated.value,
        trace_id=trace_id,
        target_type="project_member",
        target_id=member.id,
        extra={
            "project_id": str(req.project_id),
            "project_role": new_role,
            "old_status": old_status,
            "new_status": new_status,
        },
        project_id=req.project_id,
    )
    await session.commit()
    return PersonProjectMembershipOut(
        membership_id=member.id,
        project_id=member.project_id,
        project_name=project.name,
        project_role=member.project_role,
        status=member.status,
        joined_at=member.joined_at,
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
    if _is_admin(caller):
        await _record_governance_denied(
            session,
            caller,
            trace_id=trace_id,
            reason="admin_business_permission_denied",
            attempted="people.project_membership.update",
        )
        raise _denied(403, "admin_business_permission_denied", "当前身份不可管理项目成员关系")
    user = await _load_person(session, user_id)
    if (
        req.status is not None
        and req.status.value == "active"
        and user.status != UserStatus.active.value
    ):
        raise _denied(422, "active_project_member_required", "仅 active 用户可加入项目")

    member = next((m for m in user.project_members if m.id == membership_id), None)
    if member is None:
        # membership 不属于该 user：404，不泄露其它用户关系细节。
        raise _denied(404, "membership_not_found", "项目成员关系不存在")

    requested_role = req.project_role.value if req.project_role is not None else member.project_role
    await _require_manage_membership(
        session,
        caller,
        trace_id,
        project_id=member.project_id,
        current_role=member.project_role,
        requested_role=requested_role,
    )

    if req.project_role is None and req.status is None:
        raise _denied(422, "no_membership_change", "至少需提供 project_role 或 status")

    old_role, old_status = member.project_role, member.status
    if req.project_role is not None:
        member.project_role = req.project_role.value
    if req.status is not None:
        member.status = req.status.value
    await session.flush()

    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.config_people_project_membership_updated.value,
        trace_id=trace_id,
        target_type="project_member",
        target_id=member.id,
        extra={
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
        membership_id=member.id,
        project_id=member.project_id,
        project_name=project_name,
        project_role=member.project_role,
        status=member.status,
        joined_at=member.joined_at,
    )


# ---------------------------------------------------------------------------
# 密码设置 / 重置
# ---------------------------------------------------------------------------
async def set_password(
    session: AsyncSession,
    caller: CallerContext,
    user_id: uuid.UUID,
    req: SetPasswordRequest,
    trace_id: str,
) -> SetPasswordResponse:
    """治理角色为用户设置 / 重置密码。

    仅总经理 / 咨询总监；不存在用户 → 404；弱密码 → 422。允许给 inactive 用户设密码，
    但 inactive 用户登录仍失败（`login_with_password` 校验 status）。审计只记安全元数据，
    **绝不**含 password / hash / salt / digest。
    """
    await _require_governance_account_management(
        session,
        caller,
        trace_id=trace_id,
        attempted="people.password.set",
        action=AuditAction.auth_password_set.value,
    )
    user = await _load_person(session, user_id)
    _director_cannot_manage_boss(caller, user)
    err = password_service.validate_password_strength(req.password)
    if err is not None:
        raise _denied(422, "weak_password", err)

    user.password_hash = password_service.hash_password(req.password)
    user.password_set_at = datetime.now(timezone.utc)
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.auth_password_set.value,
        trace_id=trace_id,
        target_type="user",
        target_id=user.id,
        extra={
            "password_set": True,
            "target_user_status": user.status,
            "actor_is_governance": True,
        },
    )
    # 改密后撤销目标用户全部活动平台会话（治理角色改自己密码时同样强制重登）。
    revoked, _ = await session_revocation.revoke_user_sessions(session, user.id)
    if revoked:
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.auth_sessions_revoked.value,
            trace_id=trace_id,
            target_type="user",
            target_id=user.id,
            extra={
                "target_user_id": str(user.id),
                "revoked_count": revoked,
                "trigger": "password_reset",
                "preserved_current_session": False,
            },
        )
    await session.commit()
    return SetPasswordResponse(
        user_id=user.id, password_set=True, password_set_at=user.password_set_at
    )


async def set_user_status(
    session: AsyncSession,
    caller: CallerContext,
    user_id: uuid.UUID,
    req: UserStatusUpdateRequest,
    trace_id: str,
) -> PersonOut:
    """启用 / 停用用户。active→inactive 联动撤销其全部活动平台会话。

    fail-closed：不能停用自己（避免 admin 自锁）；不能停用最后一个可用 admin。停用后该用户
    立即下线（会话撤销）且登录校验 status 失败。审计只记安全元数据。"""
    await _require_governance_account_management(
        session,
        caller,
        trace_id=trace_id,
        attempted="people.user_status.update",
        action=AuditAction.config_people_status_updated.value,
    )
    new_status = req.status.value
    user = await _load_person(session, user_id)  # 预加载 company_roles（避免异步惰性加载）
    _director_cannot_manage_boss(caller, user)
    if new_status == UserStatus.inactive.value and user.id == caller.user_id:
        raise _denied(409, "cannot_deactivate_self", "不能停用当前登录的自己")

    old_status = user.status
    deactivating = old_status == UserStatus.active.value and new_status == UserStatus.inactive.value
    # 不允许从账号入口停用最后一个可用 admin / 总经理（与角色停用同口径）。
    if deactivating:
        active_roles = {
            r.company_role for r in user.company_roles if r.status == RoleStatus.active.value
        }
        for protected_role, reason, label in (
            (CompanyRole.admin.value, "last_active_admin_protected", "admin"),
            (CompanyRole.boss.value, "last_active_boss_protected", "总经理"),
        ):
            if (
                protected_role in active_roles
                and await _usable_role_count(session, protected_role) <= 1
            ):
                await audit_service.record_denied(
                    session,
                    caller=caller,
                    log_type=AuditLogType.exception,
                    action=AuditAction.config_people_status_updated.value,
                    trace_id=trace_id,
                    target_type="people_governance",
                    extra={
                        "denied_reason": reason,
                        "attempted": "people.user_status.deactivate",
                    },
                )
                raise _denied(409, reason, f"不能停用最后一个可用 {label}")

    user.status = new_status
    await session.flush()
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.config_people_status_updated.value,
        trace_id=trace_id,
        target_type="user",
        target_id=user.id,
        extra={"target_user_id": str(user.id), "old_status": old_status, "new_status": new_status},
    )
    # 停用 → 撤销目标用户全部活动平台会话（强制下线）。
    if deactivating:
        revoked, _ = await session_revocation.revoke_user_sessions(session, user.id)
        if revoked:
            await audit_service.record_event(
                session,
                caller=caller,
                log_type=AuditLogType.operation,
                action=AuditAction.auth_sessions_revoked.value,
                trace_id=trace_id,
                target_type="user",
                target_id=user.id,
                extra={
                    "target_user_id": str(user.id),
                    "revoked_count": revoked,
                    "trigger": "user_deactivated",
                    "preserved_current_session": False,
                },
            )
    await session.commit()
    return await get_person(session, caller, user_id)


# ============================================================
# 项目成员关系物理删除
# ============================================================


async def remove_project_membership(
    session: AsyncSession,
    caller: CallerContext,
    user_id: uuid.UUID,
    membership_id: uuid.UUID,
    trace_id: str,
) -> None:
    """物理删除项目成员关系（区别于 status=inactive 的软停用）。

    权限沿用 ``can_assign_project_role``：
    - 项目经理可删除本项目 coach/consultant；
    - 总经理 / 咨询总监可删除 project_manager；
    - admin 无业务管理权。

    保护：
    - 不能删除自己；
    - 项目仍 active 时不能删除最后一个 active 项目经理。
    """
    if _is_admin(caller):
        await _record_governance_denied(
            session,
            caller,
            trace_id=trace_id,
            reason="admin_business_permission_denied",
            attempted="people.project_membership.remove",
        )
        raise _denied(403, "admin_business_permission_denied", "当前身份不可删除项目成员关系")

    user = await _load_person(session, user_id)
    member = next((m for m in user.project_members if m.id == membership_id), None)
    if member is None:
        raise _denied(404, "membership_not_found", "项目成员关系不存在")

    # 保护 1：不能删除自己。
    if member.user_id == caller.user_id:
        raise _denied(409, "cannot_remove_self", "不能删除当前登录的自己")

    # 权限校验：复用 can_assign_project_role（删除 = 管辖权）。
    await _require_manage_membership(
        session,
        caller,
        trace_id,
        project_id=member.project_id,
        current_role=member.project_role,
        requested_role=member.project_role,
    )

    # 保护 2：项目仍 active 时不能删除最后一个 active 项目经理。
    project = member.project
    if (
        project is not None
        and project.status == ProjectStatus.active.value
        and member.project_role == ProjectRole.project_manager.value
        and member.status == MemberStatus.active.value
    ):
        remaining = (
            (
                await session.execute(
                    select(ProjectMember.id).where(
                        ProjectMember.project_id == member.project_id,
                        ProjectMember.id != membership_id,
                        ProjectMember.project_role == ProjectRole.project_manager.value,
                        ProjectMember.status == MemberStatus.active.value,
                    )
                )
            )
            .scalars()
            .first()
        )
        if remaining is None:
            raise _denied(
                409,
                "last_project_manager_protected",
                "不能删除项目最后一个项目经理",
            )

    old_role, old_status = member.project_role, member.status
    await session.execute(delete(ProjectMember).where(ProjectMember.id == membership_id))

    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.config_people_project_membership_removed.value,
        trace_id=trace_id,
        target_type="project_member",
        target_id=membership_id,
        before={"project_role": old_role, "status": old_status},
        after={"removed": True},
        extra={"target_user_id": str(user_id)},
        project_id=member.project_id,
    )
    await session.commit()
    return None

"""项目设置 / 项目成员治理服务。

复用既有 `projects` / `project_members` / `users` / `user_company_roles` 表。项目角色只来自
active `project_members`（与 build_caller_context 一致）；公司治理角色可读取成员治理元数据并
任命项目经理，但不因此获得项目知识库或项目设置写权。admin 不获得项目业务读写权。

安全：响应 / 审计绝不含 wecom_user_id 明文 / token / OAuth code·state / access_token /
微盘 file_id·download_url / storage_ref / source_file_ref / WeKnora id / provider 内部标识 /
业务原文。`wecom_group_id` 全文绝不进响应与审计——响应只回 bound + 脱敏 label，审计只记 bound。
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.identity import Project, ProjectMember, User
from app.schemas.enums import (
    AuditAction,
    AuditLogType,
    MemberStatus,
    ProjectRole,
    RoleStatus,
)
from app.schemas.permission import CallerContext
from app.schemas.project_settings import (
    ProjectMemberCreateRequest,
    ProjectMemberOut,
    ProjectMemberPatchRequest,
    ProjectMembersResponse,
    ProjectSettingsOut,
    ProjectSettingsUpdateRequest,
)
from app.services import audit as audit_service
from app.services import governance_policy

# 拥有项目设置写权的项目角色。
_MANAGEMENT_ROLES = {ProjectRole.project_manager.value}


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"denied_reason": reason, "message": message}
    )


def _is_admin(caller: CallerContext) -> bool:
    return governance_policy.is_admin(caller)


def _is_governance(caller: CallerContext) -> bool:
    return governance_policy.is_governance(caller)


def _caller_role(caller: CallerContext, project_id: uuid.UUID) -> str | None:
    """调用人在该项目的 active 项目角色（None = 非该项目 active 成员）。"""
    return caller.active_project_roles.get(project_id)


def _wecom_label(wecom_group_id: str | None) -> str | None:
    """企微群脱敏 label：只回末 4 位后缀，绝不回全文。无绑定 → None。"""
    if not wecom_group_id:
        return None
    tail = wecom_group_id[-4:] if len(wecom_group_id) >= 4 else wecom_group_id
    return f"···{tail}"


async def _load_project(session: AsyncSession, project_id: uuid.UUID) -> Project:
    project = (
        await session.execute(select(Project).where(Project.id == project_id))
    ).scalar_one_or_none()
    if project is None:
        raise _denied(404, "project_not_found", "项目不存在")
    return project


async def _require_read(caller: CallerContext, project_id: uuid.UUID) -> None:
    """读项目治理元数据：治理角色或本项目 active 成员；纯 admin 无业务读取权。"""
    if _is_governance(caller):
        return
    if _caller_role(caller, project_id) is not None:
        return
    raise _denied(403, "project_membership_required", "非本项目成员，无项目设置查看权")


def _can_write(caller: CallerContext, project_id: uuid.UUID) -> bool:
    """项目设置写权只来自本项目 active project_manager。"""
    return governance_policy.is_project_manager(caller, project_id)


def _can_manage_members(caller: CallerContext, project_id: uuid.UUID) -> bool:
    return _is_governance(caller) or governance_policy.is_project_manager(caller, project_id)


def _require_write(caller: CallerContext, project_id: uuid.UUID) -> None:
    """写项目设置 / 成员的权限闸门，区分安全 denied_reason。"""
    if _can_write(caller, project_id):
        return
    role = _caller_role(caller, project_id)
    # admin 系统身份：不因系统身份获得项目业务管理权。
    if _is_admin(caller) and role is None:
        raise _denied(403, "admin_business_permission_denied", "admin 不可修改项目业务设置")
    if role == ProjectRole.consultant.value:
        raise _denied(403, "project_settings_write_forbidden", "顾问成员只读，无项目设置修改权")
    # 非成员（且非治理 / 非 admin）：不泄露存在性细节，统一 membership_required。
    raise _denied(403, "project_membership_required", "非本项目成员，无项目设置修改权")


async def _coach_name(session: AsyncSession, project: Project) -> str | None:
    """由 active project_members.project_role=coach 推导辅导老师姓名（多名取首个）。"""
    row = (
        (
            await session.execute(
                select(User.name)
                .join(ProjectMember, ProjectMember.user_id == User.id)
                .where(
                    ProjectMember.project_id == project.id,
                    ProjectMember.project_role == ProjectRole.coach.value,
                    ProjectMember.status == MemberStatus.active.value,
                )
                .order_by(ProjectMember.joined_at)
            )
        )
        .scalars()
        .first()
    )
    return row


def _settings_out(project: Project, coach_name: str | None, can_write: bool) -> ProjectSettingsOut:
    return ProjectSettingsOut(
        project_id=project.id,
        name=project.name,
        status=project.status,
        client_name=project.client_name,
        coach_name=coach_name,
        lifecycle_route_key=project.lifecycle_route_key,
        lifecycle_phase_key=project.lifecycle_phase_key,
        force_review_on_ingest=project.force_review_on_ingest,
        wecom_group_bound=bool(project.wecom_group_id),
        wecom_group_label=_wecom_label(project.wecom_group_id),
        updated_at=project.updated_at,
        can_write=can_write,
    )


async def get_settings(
    session: AsyncSession, caller: CallerContext, project_id: uuid.UUID
) -> ProjectSettingsOut:
    project = await _load_project(session, project_id)
    await _require_read(caller, project_id)
    coach = await _coach_name(session, project)
    return _settings_out(project, coach, _can_write(caller, project_id))


async def update_settings(
    session: AsyncSession,
    caller: CallerContext,
    project_id: uuid.UUID,
    req: ProjectSettingsUpdateRequest,
    trace_id: str,
) -> ProjectSettingsOut:
    project = await _load_project(session, project_id)
    _require_write(caller, project_id)

    before: dict = {}
    after: dict = {}
    changed_fields: list[str] = []

    if (
        req.lifecycle_route_key is not None
        and req.lifecycle_route_key != project.lifecycle_route_key
    ):
        before["lifecycle_route_key"] = project.lifecycle_route_key
        project.lifecycle_route_key = req.lifecycle_route_key
        after["lifecycle_route_key"] = project.lifecycle_route_key
        changed_fields.append("lifecycle_route_key")
    if (
        req.lifecycle_phase_key is not None
        and req.lifecycle_phase_key != project.lifecycle_phase_key
    ):
        before["lifecycle_phase_key"] = project.lifecycle_phase_key
        project.lifecycle_phase_key = req.lifecycle_phase_key
        after["lifecycle_phase_key"] = project.lifecycle_phase_key
        changed_fields.append("lifecycle_phase_key")
    if (
        req.force_review_on_ingest is not None
        and req.force_review_on_ingest != project.force_review_on_ingest
    ):
        before["force_review_on_ingest"] = project.force_review_on_ingest
        project.force_review_on_ingest = bool(req.force_review_on_ingest)
        after["force_review_on_ingest"] = project.force_review_on_ingest
        changed_fields.append("force_review_on_ingest")
    if req.wecom_group_id is not None:
        # 空串视为解绑；只记 bound 变化，绝不把 wecom_group_id 全文写入审计 / 响应。
        new_value = req.wecom_group_id.strip() or None
        old_bound = bool(project.wecom_group_id)
        new_bound = bool(new_value)
        if new_value != project.wecom_group_id:
            project.wecom_group_id = new_value
            changed_fields.append("wecom_group_id")
            before["wecom_group_bound"] = old_bound
            after["wecom_group_bound"] = new_bound

    if not changed_fields:
        raise _denied(422, "no_settings_change", "未提供任何可更新的设置")

    await session.flush()
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.project_settings_updated.value,
        trace_id=trace_id,
        target_type="project",
        target_id=project.id,
        before=before,
        after=after,
        # extra 只含安全字段名；绝不含 wecom_group_id 全文。
        extra={"changed_fields": changed_fields},
        project_id=project.id,
    )
    await session.commit()
    coach = await _coach_name(session, project)
    return _settings_out(project, coach, _can_write(caller, project_id))


async def list_members(
    session: AsyncSession, caller: CallerContext, project_id: uuid.UUID
) -> ProjectMembersResponse:
    await _load_project(session, project_id)
    await _require_read(caller, project_id)

    rows = list(
        (
            await session.execute(
                select(ProjectMember)
                .where(ProjectMember.project_id == project_id)
                .options(selectinload(ProjectMember.user).selectinload(User.company_roles))
                .order_by(ProjectMember.joined_at)
            )
        )
        .scalars()
        .all()
    )
    items = [
        ProjectMemberOut(
            member_id=m.id,
            user_id=m.user_id,
            name=m.user.name,
            email=m.user.email,
            company_roles=[
                c.company_role for c in m.user.company_roles if c.status == RoleStatus.active.value
            ],
            project_role=m.project_role,
            status=m.status,
            joined_at=m.joined_at,
            wecom_bound=m.user.wecom_user_id is not None,
        )
        for m in rows
    ]
    return ProjectMembersResponse(
        items=items, total=len(items), can_manage=_can_manage_members(caller, project_id)
    )


def _member_out(member: ProjectMember) -> ProjectMemberOut:
    return ProjectMemberOut(
        member_id=member.id,
        user_id=member.user_id,
        name=member.user.name,
        email=member.user.email,
        company_roles=[
            role.company_role
            for role in member.user.company_roles
            if role.status == RoleStatus.active.value
        ],
        project_role=member.project_role,
        status=member.status,
        joined_at=member.joined_at,
        wecom_bound=member.user.wecom_user_id is not None,
    )


async def add_member(
    session: AsyncSession,
    caller: CallerContext,
    project_id: uuid.UUID,
    req: ProjectMemberCreateRequest,
    trace_id: str,
) -> ProjectMemberOut:
    await _load_project(session, project_id)
    user = await _load_active_business_user(session, req.user_id, role_field="project_member")
    current = (
        await session.execute(
            select(ProjectMember)
            .where(ProjectMember.project_id == project_id, ProjectMember.user_id == req.user_id)
            .options(selectinload(ProjectMember.user).selectinload(User.company_roles))
        )
    ).scalar_one_or_none()
    requested_role = req.project_role.value
    if not governance_policy.can_assign_project_role(
        caller,
        project_id,
        current_role=current.project_role if current else None,
        requested_role=requested_role,
    ):
        reason = (
            "admin_business_permission_denied"
            if _is_admin(caller)
            else "project_member_management_forbidden"
        )
        raise _denied(403, reason, "当前身份不可新增该项目成员")
    company_roles = {
        role.company_role for role in user.company_roles if role.status == RoleStatus.active.value
    }
    if requested_role == ProjectRole.coach.value and not governance_policy.coach_candidate_allowed(
        company_roles
    ):
        raise _denied(422, "coach_candidate_role_required", "辅导老师默认须由总经理或咨询总监担任")

    old = None
    if current is None:
        current = ProjectMember(
            project_id=project_id,
            user_id=user.id,
            project_role=requested_role,
            status=req.status.value,
        )
        session.add(current)
    else:
        old = {"project_role": current.project_role, "status": current.status}
        current.project_role = requested_role
        current.status = req.status.value
    await session.flush()
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.project_member_updated.value,
        trace_id=trace_id,
        target_type="project_member",
        target_id=current.id,
        before=old,
        after={"project_role": current.project_role, "status": current.status},
        extra={"target_user_id": str(user.id)},
        project_id=project_id,
    )
    await session.commit()
    current = (
        await session.execute(
            select(ProjectMember)
            .where(ProjectMember.id == current.id)
            .options(selectinload(ProjectMember.user).selectinload(User.company_roles))
        )
    ).scalar_one()
    return _member_out(current)


async def patch_member(
    session: AsyncSession,
    caller: CallerContext,
    project_id: uuid.UUID,
    member_id: uuid.UUID,
    req: ProjectMemberPatchRequest,
    trace_id: str,
) -> ProjectMemberOut:
    await _load_project(session, project_id)
    if req.project_role is None and req.status is None:
        raise _denied(422, "no_member_change", "至少需提供 project_role 或 status")

    member = (
        await session.execute(
            select(ProjectMember)
            .where(ProjectMember.id == member_id, ProjectMember.project_id == project_id)
            .options(selectinload(ProjectMember.user).selectinload(User.company_roles))
        )
    ).scalar_one_or_none()
    if member is None:
        # 不属于该项目 / 不存在：404，不泄露其它项目成员细节。
        raise _denied(404, "member_not_found", "项目成员不存在")

    old_role, old_status = member.project_role, member.status
    new_role = req.project_role.value if req.project_role is not None else old_role
    new_status = req.status.value if req.status is not None else old_status

    if not governance_policy.can_assign_project_role(
        caller,
        project_id,
        current_role=old_role,
        requested_role=new_role,
    ):
        reason = (
            "admin_business_permission_denied"
            if _is_admin(caller)
            else "project_member_management_forbidden"
        )
        raise _denied(403, reason, "当前身份不可调整该项目成员")
    target_company_roles = {
        role.company_role
        for role in member.user.company_roles
        if role.status == RoleStatus.active.value
    }
    if new_role == ProjectRole.coach.value and not governance_policy.coach_candidate_allowed(
        target_company_roles
    ):
        raise _denied(422, "coach_candidate_role_required", "辅导老师默认须由总经理或咨询总监担任")

    # 保护：变更后项目仍须至少有一个 active 项目经理。
    if (old_role in _MANAGEMENT_ROLES and old_status == MemberStatus.active.value) and not (
        new_role in _MANAGEMENT_ROLES and new_status == MemberStatus.active.value
    ):
        remaining = (
            (
                await session.execute(
                    select(ProjectMember.id).where(
                        ProjectMember.project_id == project_id,
                        ProjectMember.id != member_id,
                        ProjectMember.project_role.in_(_MANAGEMENT_ROLES),
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
                "不能停用 / 降级项目最后一个项目经理",
            )

    member.project_role = new_role
    member.status = new_status
    await session.flush()

    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.project_member_updated.value,
        trace_id=trace_id,
        target_type="project_member",
        target_id=member.id,
        before={"project_role": old_role, "status": old_status},
        after={"project_role": new_role, "status": new_status},
        extra={"target_user_id": str(member.user_id)},
        project_id=project_id,
    )
    await session.commit()
    return _member_out(member)


# ----- 项目列表 / 创建 -----
from app.services.permission import build_caller_context  # noqa: E402


async def _load_active_business_user(session: AsyncSession, user_id: uuid.UUID, *, role_field: str):
    """加载并校验一个 active 业务用户（含 active 业务公司角色，非纯 admin）。"""
    user = (
        await session.execute(
            select(User)
            .where(User.id == user_id)
            .options(
                selectinload(User.company_roles),
                selectinload(User.project_members),
            )
        )
    ).scalar_one_or_none()
    if user is None:
        raise _denied(422, f"{role_field}_not_found", "指定用户不存在")
    ctx = build_caller_context(user)
    if not ctx.is_active:
        raise _denied(422, f"{role_field}_inactive", "指定用户已停用")
    if not ctx.is_business_user:
        raise _denied(422, f"{role_field}_not_business", "指定用户必须是业务用户（纯 admin 不可）")
    return user


def _list_item_out(project: Project, project_role: str):
    from app.schemas.project_settings import ProjectListItemOut

    return ProjectListItemOut(
        id=project.id,
        name=project.name,
        client_name=project.client_name,
        status=project.status,
        lifecycle_route_key=project.lifecycle_route_key,
        lifecycle_phase_key=project.lifecycle_phase_key,
        created_at=project.created_at,
        project_role=project_role,
        can_manage=project_role == ProjectRole.project_manager.value,
    )


async def list_projects(session: AsyncSession, caller: CallerContext):
    """Return active projects from active membership only."""
    from app.schemas.project_settings import ProjectListResponse

    rows = (
        await session.execute(
            select(ProjectMember, Project)
            .join(Project, Project.id == ProjectMember.project_id)
            .where(
                ProjectMember.user_id == caller.user_id,
                ProjectMember.status == MemberStatus.active.value,
                Project.status == "active",
            )
            .order_by(Project.name, Project.id)
        )
    ).all()
    return ProjectListResponse(
        items=[_list_item_out(project, membership.project_role) for membership, project in rows]
    )


async def create_project(
    session: AsyncSession,
    caller: CallerContext,
    req,
    trace_id: str,
    *,
    weknora=None,
):
    """创建项目知识空间（仅总经理 / 咨询总监）。

    写入真实 `projects` 行 + 至少一条 active project_manager `project_members`（可选 coach）。
    纯 admin 不可创建业务项目。

    项目主事务提交后，**尝试预创建并初始化** project WeKnora KB（`ensure_project_kb`，
    best-effort）。底座未配置 / 建库 / 初始化失败**绝不**导致项目创建失败——项目正常创建，
    只在底座侧留 init_failed 映射，首次入库会自动重试。`weknora` 由 API 层注入（测试可注 fake），
    缺省 None 时跳过预建（仍保留入库时懒创建兜底）。
    """
    if not _is_governance(caller):
        if _is_admin(caller):
            raise _denied(403, "admin_business_permission_denied", "admin 不可创建业务项目")
        raise _denied(403, "project_create_forbidden", "仅总经理或咨询总监可创建项目知识库")

    name = (req.name or "").strip()
    if not name:
        raise _denied(422, "project_name_required", "项目名称不能为空")
    if len(name) > 200:
        raise _denied(422, "project_name_too_long", "项目名称过长（最多 200 字）")
    # 同名 active 项目去重（稳定策略：禁止重名 active 项目）。
    dup = (
        await session.execute(
            select(Project.id).where(Project.name == name, Project.status == "active")
        )
    ).scalar_one_or_none()
    if dup is not None:
        raise _denied(422, "project_name_conflict", "已存在同名的进行中项目")

    pm = await _load_active_business_user(
        session, req.project_manager_user_id, role_field="project_manager"
    )
    coach = None
    if req.coach_user_id is not None:
        coach = await _load_active_business_user(session, req.coach_user_id, role_field="coach")
        coach_roles = {
            role.company_role
            for role in coach.company_roles
            if role.status == RoleStatus.active.value
        }
        if not governance_policy.coach_candidate_allowed(coach_roles):
            raise _denied(
                422, "coach_candidate_role_required", "辅导老师默认须由总经理或咨询总监担任"
            )

    project = Project(
        name=name,
        client_name=(req.client_name or None),
        status="active",
        lifecycle_route_key=req.lifecycle_route_key or "route_A",
        lifecycle_phase_key=req.lifecycle_phase_key,
    )
    session.add(project)
    await session.flush()  # 取得 project.id

    session.add(
        ProjectMember(
            user_id=pm.id,
            project_id=project.id,
            project_role=ProjectRole.project_manager.value,
            status=MemberStatus.active.value,
        )
    )
    if coach is not None and coach.id != pm.id:
        session.add(
            ProjectMember(
                user_id=coach.id,
                project_id=project.id,
                project_role=ProjectRole.coach.value,
                status=MemberStatus.active.value,
            )
        )

    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.project_created.value,
        trace_id=trace_id,
        target_type="project",
        target_id=project.id,
        after={
            "name": project.name,
            "client_name": project.client_name,
            "status": project.status,
            "lifecycle_route_key": project.lifecycle_route_key,
            "project_manager_user_id": str(pm.id),
            "coach_user_id": str(coach.id) if coach is not None else None,
        },
        project_id=project.id,
    )
    await session.commit()

    from app.schemas.project_settings import ProjectCreateResponse

    # 先固化响应（best-effort 预建 KB 失败时会 rollback 使 project 过期，异步 session 不能隐式刷新）。
    response = ProjectCreateResponse(
        id=project.id,
        name=project.name,
        client_name=project.client_name,
        status=project.status,
        lifecycle_route_key=project.lifecycle_route_key,
        lifecycle_phase_key=project.lifecycle_phase_key,
        project_manager_user_id=pm.id,
        coach_user_id=coach.id if coach is not None else None,
        created_at=project.created_at,
    )

    # 项目已落库，预创建并初始化 project KB（best-effort，不阻断、不外泄底座标识）。
    if weknora is not None:
        from app.services.weknora_kb import ensure_project_kb

        await ensure_project_kb(session, weknora, project_id=response.id, trace_id=trace_id)

    return response

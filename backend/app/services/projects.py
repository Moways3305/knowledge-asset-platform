"""项目设置 / 项目成员治理服务（PBC-04）。

复用既有 `projects` / `project_members` / `users` / `user_company_roles` 表。项目角色只来自
active `project_members`（与 build_caller_context 一致）；公司治理角色（boss / 咨询总监）可跨项目读写；
admin 是系统身份——可读安全元数据，但**不**因系统身份获得项目业务管理权（写一律 403）。

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
    CompanyRole,
    MemberStatus,
    ProjectRole,
    RoleStatus,
)
from app.schemas.permission import CallerContext
from app.schemas.project_settings import (
    ProjectMemberOut,
    ProjectMemberPatchRequest,
    ProjectMembersResponse,
    ProjectSettingsOut,
    ProjectSettingsUpdateRequest,
)
from app.services import audit as audit_service

# 拥有项目设置写权的项目角色。
_MANAGEMENT_ROLES = {ProjectRole.project_manager.value, ProjectRole.coach.value}


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"denied_reason": reason, "message": message})


def _is_admin(caller: CallerContext) -> bool:
    return CompanyRole.admin.value in caller.active_company_roles


def _is_governance(caller: CallerContext) -> bool:
    # 业务治理角色 = boss / consulting_director（与可发现 L5 一致），可跨项目读写项目设置。
    return caller.can_discover_l5


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
    """读项目设置 / 成员：admin / 治理角色 / 本项目 active 成员。其余 → 403 membership_required。"""
    if _is_admin(caller) or _is_governance(caller):
        return
    if _caller_role(caller, project_id) is not None:
        return
    raise _denied(403, "project_membership_required", "非本项目成员，无项目设置查看权")


def _can_write(caller: CallerContext, project_id: uuid.UUID) -> bool:
    """是否有项目设置 / 成员写权：治理角色 或 本项目 project_manager/coach。"""
    if _is_governance(caller):
        return True
    return _caller_role(caller, project_id) in _MANAGEMENT_ROLES


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
    ).scalars().first()
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

    if req.lifecycle_route_key is not None and req.lifecycle_route_key != project.lifecycle_route_key:
        before["lifecycle_route_key"] = project.lifecycle_route_key
        project.lifecycle_route_key = req.lifecycle_route_key
        after["lifecycle_route_key"] = project.lifecycle_route_key
        changed_fields.append("lifecycle_route_key")
    if req.lifecycle_phase_key is not None and req.lifecycle_phase_key != project.lifecycle_phase_key:
        before["lifecycle_phase_key"] = project.lifecycle_phase_key
        project.lifecycle_phase_key = req.lifecycle_phase_key
        after["lifecycle_phase_key"] = project.lifecycle_phase_key
        changed_fields.append("lifecycle_phase_key")
    if req.force_review_on_ingest is not None and req.force_review_on_ingest != project.force_review_on_ingest:
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
        session, caller=caller, log_type=AuditLogType.operation,
        action=AuditAction.project_settings_updated.value, trace_id=trace_id,
        target_type="project", target_id=project.id,
        before=before, after=after,
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
        ).scalars().all()
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
        items=items, total=len(items), can_manage=_can_write(caller, project_id)
    )


async def patch_member(
    session: AsyncSession,
    caller: CallerContext,
    project_id: uuid.UUID,
    member_id: uuid.UUID,
    req: ProjectMemberPatchRequest,
    trace_id: str,
) -> ProjectMemberOut:
    await _load_project(session, project_id)
    _require_write(caller, project_id)

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

    # 保护：变更后项目仍须至少有一个 active 管理角色（project_manager / coach），
    # 否则项目失去资产确认 / 入库策略治理能力。
    if (old_role in _MANAGEMENT_ROLES and old_status == MemberStatus.active.value) and not (
        new_role in _MANAGEMENT_ROLES and new_status == MemberStatus.active.value
    ):
        remaining = (
            await session.execute(
                select(ProjectMember.id).where(
                    ProjectMember.project_id == project_id,
                    ProjectMember.id != member_id,
                    ProjectMember.project_role.in_(_MANAGEMENT_ROLES),
                    ProjectMember.status == MemberStatus.active.value,
                )
            )
        ).scalars().first()
        if remaining is None:
            raise _denied(
                409, "last_project_manager_protected",
                "不能停用 / 降级项目最后一个管理角色（project_manager / coach）",
            )

    member.project_role = new_role
    member.status = new_status
    await session.flush()

    await audit_service.record_event(
        session, caller=caller, log_type=AuditLogType.operation,
        action=AuditAction.project_member_updated.value, trace_id=trace_id,
        target_type="project_member", target_id=member.id,
        before={"project_role": old_role, "status": old_status},
        after={"project_role": new_role, "status": new_status},
        extra={"target_user_id": str(member.user_id)},
        project_id=project_id,
    )
    await session.commit()
    return ProjectMemberOut(
        member_id=member.id,
        user_id=member.user_id,
        name=member.user.name,
        email=member.user.email,
        company_roles=[
            c.company_role for c in member.user.company_roles if c.status == RoleStatus.active.value
        ],
        project_role=member.project_role,
        status=member.status,
        joined_at=member.joined_at,
        wecom_bound=member.user.wecom_user_id is not None,
    )


# ----- 项目列表 / 创建（PBC-10B） -----
from app.services.permission import build_caller_context  # noqa: E402


async def _load_active_business_user(session: AsyncSession, user_id: uuid.UUID, *, role_field: str):
    """加载并校验一个 active 业务用户（含 active 业务公司角色，非纯 admin）。"""
    user = (
        await session.execute(
            select(User).where(User.id == user_id).options(
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


def _list_item_out(project: Project, can_manage: bool):
    from app.schemas.project_settings import ProjectListItemOut

    return ProjectListItemOut(
        id=project.id, name=project.name, client_name=project.client_name,
        status=project.status, lifecycle_route_key=project.lifecycle_route_key,
        lifecycle_phase_key=project.lifecycle_phase_key, created_at=project.created_at,
        can_manage=can_manage,
    )


async def list_projects(session: AsyncSession, caller: CallerContext):
    """项目列表：治理角色 / admin 看全部 active 项目；普通业务用户看本人 active 项目。"""
    from app.schemas.project_settings import ProjectListResponse

    if _is_governance(caller) or _is_admin(caller):
        rows = list(
            (
                await session.execute(
                    select(Project).where(Project.status == "active").order_by(Project.name)
                )
            ).scalars().all()
        )
    else:
        pids = caller.active_project_ids
        if not pids:
            return ProjectListResponse(items=[])
        rows = list(
            (
                await session.execute(
                    select(Project)
                    .where(Project.status == "active", Project.id.in_(pids))
                    .order_by(Project.name)
                )
            ).scalars().all()
        )
    return ProjectListResponse(
        items=[_list_item_out(p, _can_write(caller, p.id)) for p in rows]
    )


async def create_project(session: AsyncSession, caller: CallerContext, req, trace_id: str):
    """创建项目知识空间（仅 boss / 咨询总监）。

    写入真实 `projects` 行 + 至少一条 active project_manager `project_members`（可选 coach）。
    纯 admin 不可创建业务项目。WeKnora KB 不在此预建——scope→KB 映射仍按现有
    `resolve_or_create_kb` 在首次入库时懒创建（项目创建不因 WeKnora 未配置而失败）。
    """
    if not _is_governance(caller):
        if _is_admin(caller):
            raise _denied(403, "admin_business_permission_denied", "admin 不可创建业务项目")
        raise _denied(403, "project_create_forbidden", "仅 Boss / 咨询总监可创建项目知识库")

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
        coach = await _load_active_business_user(
            session, req.coach_user_id, role_field="coach"
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
            user_id=pm.id, project_id=project.id,
            project_role=ProjectRole.project_manager.value,
            status=MemberStatus.active.value,
        )
    )
    if coach is not None and coach.id != pm.id:
        session.add(
            ProjectMember(
                user_id=coach.id, project_id=project.id,
                project_role=ProjectRole.coach.value,
                status=MemberStatus.active.value,
            )
        )

    await audit_service.record_event(
        session, caller=caller, log_type=AuditLogType.operation,
        action=AuditAction.project_created.value, trace_id=trace_id,
        target_type="project", target_id=project.id,
        after={
            "name": project.name, "client_name": project.client_name,
            "status": project.status, "lifecycle_route_key": project.lifecycle_route_key,
            "project_manager_user_id": str(pm.id),
            "coach_user_id": str(coach.id) if coach is not None else None,
        },
        project_id=project.id,
    )
    await session.commit()

    from app.schemas.project_settings import ProjectCreateResponse

    return ProjectCreateResponse(
        id=project.id, name=project.name, client_name=project.client_name,
        status=project.status, lifecycle_route_key=project.lifecycle_route_key,
        lifecycle_phase_key=project.lifecycle_phase_key,
        project_manager_user_id=pm.id,
        coach_user_id=coach.id if coach is not None else None,
        created_at=project.created_at,
    )

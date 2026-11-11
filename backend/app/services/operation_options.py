"""Administration selectors independent of any ingestion provider.

Preserve the previous selector permissions: global operators see active business
users/projects; project managers see only their managed projects and members.
Selecting an item never grants permission to perform the subsequent operation.
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.identity import Project, User
from app.schemas.enums import CompanyRole, ProjectRole
from app.schemas.operation_options import (
    OperationProjectOption,
    OperationProjectOptions,
    OperationUserOption,
    OperationUserOptions,
)
from app.schemas.permission import CallerContext
from app.services.permission import build_caller_context


def _scope(caller: CallerContext) -> tuple[bool, set[uuid.UUID]]:
    global_operator = (
        CompanyRole.admin.value in caller.active_company_roles or caller.can_discover_l5
    )
    projects = {
        project_id
        for project_id, role in caller.active_project_roles.items()
        if role == ProjectRole.project_manager.value
    }
    if not global_operator and not projects:
        raise HTTPException(
            403,
            detail={
                "denied_reason": "operation_options_forbidden",
                "message": "无权查看管理候选项",
            },
        )
    return global_operator, projects


async def list_projects(session: AsyncSession, caller: CallerContext) -> OperationProjectOptions:
    global_operator, projects = _scope(caller)
    query = select(Project.id, Project.name).where(Project.status == "active")
    if not global_operator:
        query = query.where(Project.id.in_(projects))
    rows = (await session.execute(query.order_by(Project.name, Project.id))).all()
    return OperationProjectOptions(
        items=[OperationProjectOption(id=r.id, name=r.name) for r in rows]
    )


async def list_users(session: AsyncSession, caller: CallerContext) -> OperationUserOptions:
    global_operator, projects = _scope(caller)
    users = (
        await session.scalars(
            select(User)
            .where(User.status == "active")
            .options(selectinload(User.company_roles), selectinload(User.project_members))
            .order_by(User.name, User.id)
        )
    ).all()
    labels = {"consultant": "顾问", "boss": "总经理", "consulting_director": "咨询总监"}
    items = []
    for user in users:
        context = build_caller_context(user)
        if not context.is_business_user:
            continue
        if not global_operator and not (context.active_project_ids & projects):
            continue
        role_label = " / ".join(v for k, v in labels.items() if k in context.active_company_roles)
        items.append(
            OperationUserOption(user_id=user.id, name=user.name, role_label=role_label or None)
        )
    return OperationUserOptions(items=items)

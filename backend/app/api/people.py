"""人员 / 公司角色 / 项目成员关系管理 API。

- GET   /api/v1/admin/people                                         （admin / boss / 咨询总监）
- GET   /api/v1/admin/people/{user_id}                               （同上）
- POST  /api/v1/admin/people/{user_id}/company-roles                 （管理公司角色）
- GET   /api/v1/admin/people/{user_id}/project-memberships           （读，含 inactive）
- POST  /api/v1/admin/people/{user_id}/project-memberships           （upsert 项目成员关系）
- PATCH /api/v1/admin/people/{user_id}/project-memberships/{id}      （更新角色 / 状态）

权限委托 service；响应只含安全身份/治理元数据，写动作均写审计。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.people import (
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
from app.services import people as people_service

router = APIRouter(prefix="/api/v1/admin/people", tags=["people"])


@router.get("", response_model=PeopleListResponse)
async def list_people(
    role: str | None = Query(default=None),
    status: str | None = Query(default=None),
    q: str | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> PeopleListResponse:
    return await people_service.list_people(
        session, caller, role=role, status=status, q=q,
        project_id=project_id, limit=limit, offset=offset,
    )


@router.get("/{user_id}", response_model=PersonOut)
async def get_person(
    user_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> PersonOut:
    return await people_service.get_person(session, caller, user_id)


@router.post("/{user_id}/company-roles", response_model=PersonOut)
async def set_company_role(
    user_id: uuid.UUID,
    req: CompanyRoleUpdateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> PersonOut:
    return await people_service.set_company_role(session, caller, user_id, req, get_trace_id(request))


@router.post("/{user_id}/password", response_model=SetPasswordResponse)
async def set_password(
    user_id: uuid.UUID,
    req: SetPasswordRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> SetPasswordResponse:
    """管理员设置 / 重置用户密码。password 仅入站、绝不回显。
    改密成功后撤销该用户全部活动平台会话（强制重登）。"""
    return await people_service.set_password(session, caller, user_id, req, get_trace_id(request))


@router.post("/{user_id}/status", response_model=PersonOut)
async def set_user_status(
    user_id: uuid.UUID,
    req: UserStatusUpdateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> PersonOut:
    """启用 / 停用用户。active→inactive 联动撤销其平台会话；
    不能停用自己 / 最后一个可用 admin。"""
    return await people_service.set_user_status(session, caller, user_id, req, get_trace_id(request))


@router.get("/{user_id}/project-memberships", response_model=list[PersonProjectMembershipOut])
async def list_project_memberships(
    user_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> list[PersonProjectMembershipOut]:
    return await people_service.list_project_memberships(session, caller, user_id)


@router.post("/{user_id}/project-memberships", response_model=PersonProjectMembershipOut)
async def upsert_project_membership(
    user_id: uuid.UUID,
    req: ProjectMembershipCreateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> PersonProjectMembershipOut:
    return await people_service.upsert_project_membership(session, caller, user_id, req, get_trace_id(request))


@router.patch(
    "/{user_id}/project-memberships/{membership_id}",
    response_model=PersonProjectMembershipOut,
)
async def patch_project_membership(
    user_id: uuid.UUID,
    membership_id: uuid.UUID,
    req: ProjectMembershipPatchRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> PersonProjectMembershipOut:
    return await people_service.patch_project_membership(
        session, caller, user_id, membership_id, req, get_trace_id(request)
    )


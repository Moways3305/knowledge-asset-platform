"""项目设置 / 项目成员管理 API（PBC-04）。

- GET   /api/v1/projects/{project_id}/settings              （admin / 治理角色 / 本项目成员可读）
- PATCH /api/v1/projects/{project_id}/settings              （project_manager·coach / 治理角色可写）
- GET   /api/v1/projects/{project_id}/members              （同读权限）
- PATCH /api/v1/projects/{project_id}/members/{member_id}  （同写权限）

权限委托 service；响应只含安全治理元数据，写动作均写审计。新增成员仍由 PBC-02
`/admin/people/{user_id}/project-memberships` 维护，本路由不提供 POST members。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.permission import CallerContext
from app.schemas.project_settings import (
    ProjectCreateRequest,
    ProjectCreateResponse,
    ProjectListResponse,
    ProjectMemberOut,
    ProjectMemberPatchRequest,
    ProjectMembersResponse,
    ProjectSettingsOut,
    ProjectSettingsUpdateRequest,
)
from app.services import projects as projects_service

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ProjectListResponse:
    """项目列表：治理角色 / admin 看全部 active 项目；业务用户看本人 active 项目。"""
    return await projects_service.list_projects(session, caller)


@router.post("", response_model=ProjectCreateResponse, status_code=201)
async def create_project(
    req: ProjectCreateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ProjectCreateResponse:
    """创建项目知识空间（仅 Boss / 咨询总监）。写入真实 projects + active project_manager 成员。"""
    return await projects_service.create_project(session, caller, req, get_trace_id(request))


@router.get("/{project_id}/settings", response_model=ProjectSettingsOut)
async def get_project_settings(
    project_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ProjectSettingsOut:
    return await projects_service.get_settings(session, caller, project_id)


@router.patch("/{project_id}/settings", response_model=ProjectSettingsOut)
async def update_project_settings(
    project_id: uuid.UUID,
    req: ProjectSettingsUpdateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ProjectSettingsOut:
    return await projects_service.update_settings(session, caller, project_id, req, get_trace_id(request))


@router.get("/{project_id}/members", response_model=ProjectMembersResponse)
async def list_project_members(
    project_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ProjectMembersResponse:
    return await projects_service.list_members(session, caller, project_id)


@router.patch("/{project_id}/members/{member_id}", response_model=ProjectMemberOut)
async def patch_project_member(
    project_id: uuid.UUID,
    member_id: uuid.UUID,
    req: ProjectMemberPatchRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ProjectMemberOut:
    return await projects_service.patch_member(
        session, caller, project_id, member_id, req, get_trace_id(request)
    )

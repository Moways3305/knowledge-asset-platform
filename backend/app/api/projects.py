"""项目设置 / 项目成员管理 API。

- GET   /api/v1/projects/{project_id}/settings              （治理角色 / 本项目成员可读）
- PATCH /api/v1/projects/{project_id}/settings              （本项目 project_manager 可写）
- GET   /api/v1/projects/{project_id}/members              （同读权限）
- POST  /api/v1/projects/{project_id}/members              （治理角色 / 本项目经理按矩阵新增）
- PATCH /api/v1/projects/{project_id}/members/{member_id}  （治理角色 / 本项目经理按矩阵调整）

权限委托 service；响应只含安全治理元数据，写动作均写审计。
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
    ProjectMemberCreateRequest,
    ProjectMemberOut,
    ProjectMemberPatchRequest,
    ProjectMembersResponse,
    ProjectSettingsOut,
    ProjectSettingsUpdateRequest,
)
from app.services import projects as projects_service
from app.services.weknora_client import (
    NullWeKnoraClient,
    WeKnoraClient,
    get_weknora_client,
)

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ProjectListResponse:
    """项目列表：治理角色看安全元数据；项目成员看本人项目；纯 admin 拒绝。"""
    result: ProjectListResponse = await projects_service.list_projects(session, caller)
    return result


@router.post("", response_model=ProjectCreateResponse, status_code=201)
async def create_project(
    req: ProjectCreateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    weknora: WeKnoraClient | NullWeKnoraClient = Depends(get_weknora_client),
) -> ProjectCreateResponse:
    """创建项目知识空间（仅总经理 / 咨询总监）。写入真实 projects + active project_manager 成员；
    随后 best-effort 预创建并初始化 project WeKnora KB。"""
    result: ProjectCreateResponse = await projects_service.create_project(
        session, caller, req, get_trace_id(request), weknora=weknora
    )
    return result


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
    return await projects_service.update_settings(
        session, caller, project_id, req, get_trace_id(request)
    )


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


@router.post("/{project_id}/members", response_model=ProjectMemberOut, status_code=201)
async def add_project_member(
    project_id: uuid.UUID,
    req: ProjectMemberCreateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ProjectMemberOut:
    return await projects_service.add_member(
        session, caller, project_id, req, get_trace_id(request)
    )

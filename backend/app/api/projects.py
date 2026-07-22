"""项目设置 / 项目成员管理 API。

- GET    /api/v1/projects                                       （本人 active 成员关系）
- POST   /api/v1/projects                                      （总经理 / 咨询总监）
- GET    /api/v1/projects/{project_id}/overview                （治理角色 / 本项目成员）
- GET    /api/v1/projects/{project_id}/settings                （同读权限）
- PATCH  /api/v1/projects/{project_id}/settings                （本项目 project_manager）
- GET    /api/v1/projects/{project_id}/members                   （同读权限）
- POST   /api/v1/projects/{project_id}/members                  （治理角色 / 本项目经理按矩阵新增）
- PATCH  /api/v1/projects/{project_id}/members/{member_id}      （治理角色 / 本项目经理按矩阵调整）
- DELETE /api/v1/projects/{project_id}/members/{member_id}      （同上权限，物理删除关系）
- POST   /api/v1/projects/{project_id}/archive                  （总经理 / 咨询总监）
- POST   /api/v1/projects/{project_id}/reactivate               （总经理 / 咨询总监）
- DELETE /api/v1/projects/{project_id}                          （仅总经理，需先归档+清空资产）

权限委托 service；响应只含安全治理元数据，写动作均写审计。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.permission import CallerContext
from app.schemas.project_settings import (
    CandidateMembersResponse,
    ProjectCreateRequest,
    ProjectCreateResponse,
    ProjectDeletionReadinessOut,
    ProjectListResponse,
    ProjectMemberCreateRequest,
    ProjectMemberOut,
    ProjectMemberPatchRequest,
    ProjectMembersResponse,
    ProjectOverviewResponse,
    ProjectSettingsOut,
    ProjectSettingsUpdateRequest,
)
from app.services import project_overview as project_overview_service
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
    """Return switchable projects from the caller's active memberships."""
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


@router.get("/{project_id}/overview", response_model=ProjectOverviewResponse)
async def get_project_overview(
    project_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ProjectOverviewResponse:
    return await project_overview_service.get_overview(session, caller, project_id)


@router.get("/{project_id}/settings", response_model=ProjectSettingsOut)
async def get_project_settings(
    project_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ProjectSettingsOut:
    return await projects_service.get_settings(session, caller, project_id)


@router.get("/{project_id}/deletion-readiness", response_model=ProjectDeletionReadinessOut)
async def get_project_deletion_readiness(
    project_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ProjectDeletionReadinessOut:
    """Return safe prerequisite counts and authorization state for the lifecycle UI."""
    return await projects_service.get_deletion_readiness(session, caller, project_id)


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


@router.get("/{project_id}/candidate-members", response_model=CandidateMembersResponse)
async def list_candidate_members(
    project_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> CandidateMembersResponse:
    """列出可被添加为项目成员的候选用户（active 业务用户，排除已 active 成员）。

    读权限同 list_members：治理角色或本项目 active 成员可读。
    """
    return await projects_service.list_candidate_members(session, caller, project_id)


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


@router.delete("/{project_id}/members/{member_id}", status_code=204)
async def remove_project_member(
    project_id: uuid.UUID,
    member_id: uuid.UUID,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    """物理删除项目成员关系（区别于 status=inactive 的软停用）。

    权限沿用成员管理矩阵：项目经理可删本项目 coach/consultant，
    总经理 / 咨询总监可删 project_manager。保护：不可删自己、不可删最后一个项目经理。
    """
    await projects_service.remove_member(
        session, caller, project_id, member_id, get_trace_id(request)
    )
    return Response(status_code=204)


@router.post("/{project_id}/archive", response_model=ProjectSettingsOut)
async def archive_project(
    project_id: uuid.UUID,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ProjectSettingsOut:
    """归档项目（仅总经理 / 咨询总监）。

    project.status → archived；全部 project_members → inactive（保留行用于审计）。
    """
    return await projects_service.archive_project(
        session, caller, project_id, get_trace_id(request)
    )


@router.post("/{project_id}/reactivate", response_model=ProjectSettingsOut)
async def reactivate_project(
    project_id: uuid.UUID,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ProjectSettingsOut:
    """重新激活已归档项目（仅总经理 / 咨询总监）。

    project.status → active；成员关系保持 inactive（需手动重新启用）。
    """
    return await projects_service.reactivate_project(
        session, caller, project_id, get_trace_id(request)
    )


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: uuid.UUID,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    weknora: WeKnoraClient | NullWeKnoraClient = Depends(get_weknora_client),
):
    """删除项目（仅总经理）。

    前置：项目必须先归档 + 项目下无未删除 KnowledgeAsset。
    执行：物理删除成员关系 + KB 映射 + 项目行；best-effort 清理底座 KB。
    """
    await projects_service.delete_project(
        session, caller, project_id, get_trace_id(request), weknora=weknora
    )
    return Response(status_code=204)

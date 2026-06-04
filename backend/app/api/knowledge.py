"""Knowledge 读 API（IMPLEMENT-04）+ 受控删除（PBC-10B）。

读：列表 / 详情 / 个人知识。删除：受控软删除 / 撤下。权限判断全部委托
`app.services.knowledge`（其内部调用集中权限服务），本层不写权限矩阵。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.knowledge import (
    KnowledgeDeleteRequest,
    KnowledgeDeleteResponse,
    KnowledgeDetailOut,
    KnowledgeListResponse,
)
from app.schemas.permission import CallerContext
from app.services import knowledge as knowledge_service
from app.services.weknora_client import get_weknora_client

router = APIRouter(prefix="/api/v1", tags=["knowledge"])


@router.get("/knowledge", response_model=KnowledgeListResponse)
async def list_knowledge(
    scope: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> KnowledgeListResponse:
    """知识列表：只返回调用人可发现的资产。"""
    items = await knowledge_service.list_knowledge(
        session, caller, scope=scope, include_archived=include_archived
    )
    return KnowledgeListResponse(items=items, total=len(items))


@router.get("/my/knowledge", response_model=KnowledgeListResponse)
async def list_my_knowledge(
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> KnowledgeListResponse:
    """个人知识：仅返回本人的 scope=personal 资产；纯 admin 返回 403。"""
    items = await knowledge_service.list_my_knowledge(session, caller)
    return KnowledgeListResponse(items=items, total=len(items))


@router.get("/knowledge/{asset_id}", response_model=KnowledgeDetailOut)
async def get_knowledge_detail(
    asset_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> KnowledgeDetailOut:
    """知识详情：discovery 被拒时按安全口径返回（l5/personal/archived → 404）。"""
    return await knowledge_service.get_detail(session, caller, asset_id)


@router.post("/knowledge/{asset_id}/delete", response_model=KnowledgeDeleteResponse)
async def delete_knowledge_asset(
    asset_id: uuid.UUID,
    body: KnowledgeDeleteRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    weknora=Depends(get_weknora_client),
) -> KnowledgeDeleteResponse:
    """受控删除 / 撤下知识资产（PBC-10B，软删除）。权限：个人 owner / 项目 active
    project_manager / 公司 boss·咨询总监；纯 admin 不可。删除后资产立即退出
    列表 / 检索 / 问答 / 预览 / Agent / 原文授权运行时。"""
    return await knowledge_service.delete_asset(
        session, caller, asset_id, reason=body.reason,
        weknora=weknora, trace_id=get_trace_id(request),
    )

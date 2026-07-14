"""Knowledge 读 API+ 受控删除。

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
    RetryIndexRequest,
    RetryIndexResponse,
)
from app.schemas.knowledge_insights import KnowledgeOpsInsightsResponse
from app.schemas.permission import CallerContext
from app.services import knowledge as knowledge_service
from app.services import knowledge_insights as insights_service
from app.services.storage import LocalFileStorage, get_storage
from app.services.weknora_client import get_weknora_client

router = APIRouter(prefix="/api/v1", tags=["knowledge"])


@router.get("/knowledge", response_model=KnowledgeListResponse)
async def list_knowledge(
    scope: str | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    include_archived: bool = Query(default=False),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> KnowledgeListResponse:
    """知识列表：只返回调用人可发现的资产。"""
    items = await knowledge_service.list_knowledge(
        session,
        caller,
        scope=scope,
        project_id=project_id,
        include_archived=include_archived,
    )
    return KnowledgeListResponse(items=items, total=len(items))


@router.get("/knowledge/ops-insights", response_model=KnowledgeOpsInsightsResponse)
async def knowledge_ops_insights(
    scope: str | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    days: int = Query(default=30),
    limit: int = Query(default=10),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> KnowledgeOpsInsightsResponse:
    """Knowledge 运营洞察：真实表安全聚合 + 安全提示。

    权限：业务用户按其可见范围、纯 admin 系统运维聚合（title_visible=false）、inactive/非业务非 admin → 403。
    不绕过 `/knowledge` 发现权限；响应绝不含 WeKnora id / 存储引用 / 原文 / 文件名 / token。"""
    return await insights_service.get_ops_insights(
        session,
        caller,
        scope=scope,
        project_id=project_id,
        days=days,
        limit=limit,
    )


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
    """受控删除 / 撤下知识资产。权限：个人 owner / 项目 active
    project_manager / 公司 boss·咨询总监；纯 admin 不可。删除后资产立即退出
    列表 / 检索 / 问答 / 预览 / Agent / 原文授权运行时。"""
    return await knowledge_service.delete_asset(
        session,
        caller,
        asset_id,
        reason=body.reason,
        weknora=weknora,
        trace_id=get_trace_id(request),
    )


@router.post("/knowledge/{asset_id}/retry-index", response_model=RetryIndexResponse)
async def retry_index(
    asset_id: uuid.UUID,
    request: Request,
    req: RetryIndexRequest | None = None,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
    weknora=Depends(get_weknora_client),
) -> RetryIndexResponse:
    """重试底座索引：仅对 index_failed / not_indexed / skipped 的资产，
    且调用人有业务管理权（个人 owner / 项目 PM·coach / 公司治理）。纯 admin 不可。
    复用 confirm 的安全索引机制；响应只回安全索引状态，绝不含 kb_id / doc_id / storage_ref。"""
    body = req or RetryIndexRequest()
    return await knowledge_service.retry_index(
        session,
        caller,
        asset_id,
        weknora=weknora,
        storage=storage,
        trace_id=get_trace_id(request),
        embedding_model_ref=body.embedding_model_ref,
        rerank_model_ref=body.rerank_model_ref,
    )

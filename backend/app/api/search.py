"""统一检索 / 问答 API。

- POST /api/v1/knowledge/search：两阶段检索 + 意图路由 + 问答自拼答案。

权限/脱敏/审计全部委托 `app.services.search`（其复用集中权限服务与检索编排）。
响应不含任何 weknora kb/doc/chunk id、内部存储引用、api_key、未脱敏原文。
该接口是外部 Agent 检索适配的底层。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.errors import denied
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.permission import CallerContext
from app.schemas.search import SearchRequest, SearchResponse
from app.services import discoverable_projects
from app.services import search as search_service
from app.services.llm_client import get_llm_client
from app.services.weknora_client import get_weknora_client

router = APIRouter(prefix="/api/v1", tags=["search"])


@router.post("/knowledge/search", response_model=SearchResponse)
async def knowledge_search(
    req: SearchRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    weknora=Depends(get_weknora_client),
    llm=Depends(get_llm_client),
) -> SearchResponse:
    if req.filters.project_id is not None:
        project = await discoverable_projects.get_knowledge_library_project(
            session,
            caller,
            req.filters.project_id,
            allowed_scope=req.scope,
        )
        if project is None:
            raise denied(404, "project_not_found", "项目不存在或不可用")
    return await search_service.run_search(
        session,
        caller,
        req,
        weknora=weknora,
        llm=llm,
        trace_id=get_trace_id(request),
        allow_cross_project=True,
    )

"""Provider 中立外部 Agent 网关（WorkBuddy 主接入面）。

平台核心是 provider 中立的 `external_agent_gateway`。本路由是中立适配面：Bearer token →
注册行 → **从 token 绑定的 bound_user_id 解析真实平台 caller**（绝不读客户端自报 user id），
再复用统一检索 / 项目服务（channel=agent）。接入注册管理（agent-whitelist）也收口在此。

安全：fail closed（无绑定 / 非 active / 非业务用户即拒）；响应不含 token / weknora id /
provider 内部标识 / storage 引用。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import denied
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.db.utils import utc_now
from app.models.agent_registry import AgentWhitelistRule
from app.schemas.agent_workbench import (
    WorkbenchKnowledgeContent,
    WorkbenchKnowledgeListResponse,
    WorkbenchKnowledgePageResponse,
    WorkbenchKnowledgeSummary,
    WorkbenchOriginalAccessResponse,
    WorkbenchProjectBrief,
    WorkbenchReviewsResponse,
    WorkbenchTagsResponse,
    WorkbenchTodosResponse,
)
from app.schemas.external_agent import (
    AgentDirectoriesResponse,
    AgentDirectoryOut,
    AgentProjectOut,
    AgentProjectsResponse,
    AgentToolSearchRequest,
)
from app.schemas.permission import AccessChannel, CallerContext
from app.schemas.search import SearchFilters, SearchRequest, SearchResponse
from app.services import agent_registry, agent_workbench
from app.services import directories as directory_service
from app.services import external_agent_gateway as gateway
from app.services import projects as projects_service
from app.services import search as search_service
from app.services.llm_client import get_llm_client
from app.services.storage import LocalFileStorage, get_storage
from app.services.weknora_client import get_weknora_client

router = APIRouter(prefix="/api/v1/agent-gateway", tags=["agent-gateway"])

_REQUIRED_CAPABILITY = "qa"


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        return None
    return parts[1].strip()


async def require_bound_caller(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db),
) -> AsyncIterator[tuple[AgentWhitelistRule, CallerContext]]:
    """Bearer → 注册行(qa) → bound_user_id → 真实 caller。任一不满足即 fail closed。

    绝不读取 X-Platform-User-Id / 任何客户端自报 caller id。
    """
    token = _bearer(authorization)
    if token is None:
        raise denied(401, "agent_unauthenticated", "缺少或非法 Bearer token")
    rule = await agent_registry.lookup_enabled_rule(session, token)
    if rule is None:
        raise denied(403, "agent_not_whitelisted", "接入未注册或未启用")
    if rule.capability != _REQUIRED_CAPABILITY:
        raise denied(403, "agent_capability_denied", "该接入未启用 qa 能力")
    if rule.bound_user_id is None:
        raise denied(403, "caller_unbound", "该 token 未绑定平台用户")
    caller = await gateway.resolve_caller(session, rule.bound_user_id)
    if caller is None or not caller.is_business_user:
        raise denied(403, "caller_unresolved", "绑定用户无法解析或非业务用户")
    try:
        yield rule, caller
    except BaseException:
        # 鉴权通过但端点失败时也不得制造“已连接”状态。
        raise
    else:
        # 只有完整成功返回的 WorkBuddy 请求才记录活动；不写审计 extra/请求内容。
        if rule.provider == "workbuddy":
            rule.last_connected_at = utc_now()
            await session.commit()


@router.post("/tools/knowledge-search", response_model=SearchResponse)
async def knowledge_search(
    req: AgentToolSearchRequest,
    request: Request,
    bound: tuple[AgentWhitelistRule, CallerContext] = Depends(require_bound_caller),
    session: AsyncSession = Depends(get_db),
    weknora=Depends(get_weknora_client),
    llm=Depends(get_llm_client),
) -> SearchResponse:
    rule, caller = bound
    # 请求未指定 scope 时自动收窄到注册行允许的范围（天花板语义，不拒绝未指定请求）
    effective_scope: str | None = req.scope
    if not effective_scope and rule.allowed_scope not in (None, "all"):
        effective_scope = rule.allowed_scope
    if not gateway.tool_scope_allowed(rule, effective_scope):
        raise denied(403, "agent_scope_denied", "请求范围超出该接入允许的 scope")
    effective_filters = dict(req.filters or {})
    if rule.allowed_project_id is not None:
        if effective_scope not in (None, "project"):
            raise denied(403, "agent_scope_denied", "项目锁定接入仅允许项目范围检索")
        effective_scope = "project"
        requested_project = effective_filters.get("project_id")
        if requested_project is not None and requested_project != str(rule.allowed_project_id):
            raise denied(403, "agent_scope_denied", "请求项目超出该接入允许范围")
        effective_filters["project_id"] = str(rule.allowed_project_id)
    search_req = SearchRequest(
        query=req.query,
        scope=effective_scope,
        intent=req.intent,
        filters=SearchFilters(**effective_filters),
        want_original=False,  # agent-gateway 永不取原文
        asset_id=None,
    )
    return await search_service.run_search(
        session,
        caller,
        search_req,
        weknora=weknora,
        llm=llm,
        trace_id=get_trace_id(request),
        channel=AccessChannel.agent,
        asset_guard=lambda asset: gateway.asset_within_ceiling(rule, asset),
    )


@router.get("/knowledge/directories", response_model=AgentDirectoriesResponse)
async def list_knowledge_directories(
    bound: tuple[AgentWhitelistRule, CallerContext] = Depends(require_bound_caller),
    session: AsyncSession = Depends(get_db),
) -> AgentDirectoriesResponse:
    rule, caller = bound
    effective_scope = "project" if rule.allowed_project_id is not None else rule.allowed_scope
    rows = await directory_service.visible_directory_rows(
        session,
        caller,
        allowed_scope=effective_scope,
        allowed_project_id=rule.allowed_project_id,
    )
    return AgentDirectoriesResponse(items=[AgentDirectoryOut(**row) for row in rows])


@router.get("/projects", response_model=AgentProjectsResponse)
async def list_accessible_projects(
    bound: tuple[AgentWhitelistRule, CallerContext] = Depends(require_bound_caller),
    session: AsyncSession = Depends(get_db),
) -> AgentProjectsResponse:
    _, caller = bound
    full = await projects_service.list_projects(session, caller)
    return AgentProjectsResponse(
        items=[AgentProjectOut(project_id=p.id, name=p.name, status=p.status) for p in full.items]
    )


# ---------------------------------------------------------------------------
# 只读工作台工具：全部经 require_bound_caller，仅安全白名单字段，绝不写。
# caller 由 token 绑定解析；权限走 decide() + 注册行天花板。无原文 / 文件 / 预览 URL。
# ---------------------------------------------------------------------------
@router.get("/todos", response_model=WorkbenchTodosResponse)
async def list_my_todos(
    limit: int | None = Query(default=None, ge=1, le=100),
    bound: tuple[AgentWhitelistRule, CallerContext] = Depends(require_bound_caller),
    session: AsyncSession = Depends(get_db),
) -> WorkbenchTodosResponse:
    rule, caller = bound
    return await agent_workbench.list_todos(session, caller, rule, limit=limit)


@router.get("/knowledge/recent", response_model=WorkbenchKnowledgeListResponse)
async def list_recent_knowledge(
    scope: str | None = Query(default=None),
    project_id: uuid.UUID | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=20),
    bound: tuple[AgentWhitelistRule, CallerContext] = Depends(require_bound_caller),
    session: AsyncSession = Depends(get_db),
) -> WorkbenchKnowledgeListResponse:
    rule, caller = bound
    return await agent_workbench.list_recent_knowledge(
        session, caller, rule, scope=scope, project_id=project_id, limit=limit
    )


@router.get("/knowledge/personal", response_model=WorkbenchKnowledgePageResponse)
async def list_my_personal_knowledge(
    request: Request,
    tags: list[str] | None = Query(default=None),
    asset_status: str | None = Query(default=None),
    updated_from: datetime | None = Query(default=None),
    updated_to: datetime | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    bound: tuple[AgentWhitelistRule, CallerContext] = Depends(require_bound_caller),
    session: AsyncSession = Depends(get_db),
) -> WorkbenchKnowledgePageResponse:
    rule, caller = bound
    return await agent_workbench.list_accessible_knowledge(
        session,
        caller,
        rule,
        tags=tags,
        asset_status=asset_status,
        updated_from=updated_from,
        updated_to=updated_to,
        offset=offset,
        limit=limit,
        personal_only=True,
        trace_id=get_trace_id(request),
    )


@router.get("/knowledge", response_model=WorkbenchKnowledgePageResponse)
async def list_accessible_knowledge(
    request: Request,
    scope: str | None = Query(default=None),
    tags: list[str] | None = Query(default=None),
    asset_status: str | None = Query(default=None),
    updated_from: datetime | None = Query(default=None),
    updated_to: datetime | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    bound: tuple[AgentWhitelistRule, CallerContext] = Depends(require_bound_caller),
    session: AsyncSession = Depends(get_db),
) -> WorkbenchKnowledgePageResponse:
    rule, caller = bound
    return await agent_workbench.list_accessible_knowledge(
        session,
        caller,
        rule,
        scope=scope,
        tags=tags,
        asset_status=asset_status,
        updated_from=updated_from,
        updated_to=updated_to,
        offset=offset,
        limit=limit,
        trace_id=get_trace_id(request),
    )


@router.get("/knowledge/tags", response_model=WorkbenchTagsResponse)
async def list_knowledge_tags(
    request: Request,
    scope: str | None = Query(default=None),
    bound: tuple[AgentWhitelistRule, CallerContext] = Depends(require_bound_caller),
    session: AsyncSession = Depends(get_db),
) -> WorkbenchTagsResponse:
    rule, caller = bound
    return await agent_workbench.list_visible_tags(
        session, caller, rule, scope=scope, trace_id=get_trace_id(request)
    )


@router.get("/knowledge/{asset_id}", response_model=WorkbenchKnowledgeSummary)
async def get_knowledge_detail(
    asset_id: uuid.UUID,
    request: Request,
    bound: tuple[AgentWhitelistRule, CallerContext] = Depends(require_bound_caller),
    session: AsyncSession = Depends(get_db),
) -> WorkbenchKnowledgeSummary:
    rule, caller = bound
    return await agent_workbench.get_knowledge_summary(
        session, caller, rule, asset_id, trace_id=get_trace_id(request)
    )


@router.get("/knowledge/{asset_id}/content", response_model=WorkbenchKnowledgeContent)
async def get_knowledge_content(
    asset_id: uuid.UUID,
    request: Request,
    offset: int = Query(default=0, ge=0),
    max_chars: int = Query(default=4000, ge=1, le=8000),
    bound: tuple[AgentWhitelistRule, CallerContext] = Depends(require_bound_caller),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
) -> WorkbenchKnowledgeContent:
    rule, caller = bound
    return await agent_workbench.get_knowledge_content(
        session,
        caller,
        rule,
        asset_id,
        storage=storage,
        offset=offset,
        max_chars=max_chars,
        trace_id=get_trace_id(request),
    )


@router.get("/knowledge/{asset_id}/summary", response_model=WorkbenchKnowledgeSummary)
async def get_knowledge_summary(
    asset_id: uuid.UUID,
    request: Request,
    bound: tuple[AgentWhitelistRule, CallerContext] = Depends(require_bound_caller),
    session: AsyncSession = Depends(get_db),
) -> WorkbenchKnowledgeSummary:
    rule, caller = bound
    return await agent_workbench.get_knowledge_summary(
        session, caller, rule, asset_id, trace_id=get_trace_id(request)
    )


@router.get("/projects/{project_id}/knowledge", response_model=WorkbenchKnowledgeListResponse)
async def list_project_knowledge(
    project_id: uuid.UUID,
    limit: int | None = Query(default=None, ge=1, le=30),
    phase: str | None = Query(default=None),
    tags: list[str] | None = Query(default=None),
    bound: tuple[AgentWhitelistRule, CallerContext] = Depends(require_bound_caller),
    session: AsyncSession = Depends(get_db),
) -> WorkbenchKnowledgeListResponse:
    rule, caller = bound
    return await agent_workbench.list_project_knowledge(
        session, caller, rule, project_id, limit=limit, phase=phase, tags=tags
    )


@router.get("/projects/{project_id}/brief", response_model=WorkbenchProjectBrief)
async def get_project_brief(
    project_id: uuid.UUID,
    bound: tuple[AgentWhitelistRule, CallerContext] = Depends(require_bound_caller),
    session: AsyncSession = Depends(get_db),
) -> WorkbenchProjectBrief:
    rule, caller = bound
    return await agent_workbench.get_project_brief(session, caller, rule, project_id)


@router.get("/reviews/pending", response_model=WorkbenchReviewsResponse)
async def list_pending_reviews(
    limit: int | None = Query(default=None, ge=1, le=20),
    bound: tuple[AgentWhitelistRule, CallerContext] = Depends(require_bound_caller),
    session: AsyncSession = Depends(get_db),
) -> WorkbenchReviewsResponse:
    rule, caller = bound
    return await agent_workbench.list_pending_reviews(session, caller, rule, limit=limit)


@router.get("/original-access/requests", response_model=WorkbenchOriginalAccessResponse)
async def list_original_access_requests(
    box: str = Query(default="mine"),
    limit: int | None = Query(default=None, ge=1, le=20),
    bound: tuple[AgentWhitelistRule, CallerContext] = Depends(require_bound_caller),
    session: AsyncSession = Depends(get_db),
) -> WorkbenchOriginalAccessResponse:
    rule, caller = bound
    return await agent_workbench.list_original_access_requests(
        session, caller, rule, box=box, limit=limit
    )

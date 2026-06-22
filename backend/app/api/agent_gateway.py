"""Provider 中立外部 Agent 网关（WorkBuddy 主接入面）。

平台核心是 provider 中立的 `external_agent_gateway`。本路由是中立适配面：Bearer token →
注册行 → **从 token 绑定的 bound_user_id 解析真实平台 caller**（绝不读客户端自报 user id），
再复用统一检索 / 项目服务（channel=agent）。Dify 路由为 legacy，不在此处。

安全：fail closed（无绑定 / 非 active / 非业务用户即拒）；响应不含 token / weknora id /
provider 内部标识 / storage 引用。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.trace import get_trace_id
from app.db.session import get_db
from app.models.agent_registry import AgentWhitelistRule
from app.schemas.external_agent import (
    AgentProjectOut,
    AgentProjectsResponse,
    AgentToolSearchRequest,
)
from app.schemas.permission import AccessChannel, CallerContext
from app.schemas.search import SearchFilters, SearchRequest, SearchResponse
from app.services import agent_registry
from app.services import external_agent_gateway as gateway
from app.services import projects as projects_service
from app.services import search as search_service
from app.services.llm_client import get_llm_client
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


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"denied_reason": reason, "message": message}
    )


async def require_bound_caller(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db),
) -> tuple[AgentWhitelistRule, CallerContext]:
    """Bearer → 注册行(qa) → bound_user_id → 真实 caller。任一不满足即 fail closed。

    绝不读取 X-Platform-User-Id / 任何客户端自报 caller id。
    """
    token = _bearer(authorization)
    if token is None:
        raise _denied(401, "agent_unauthenticated", "缺少或非法 Bearer token")
    rule = await agent_registry.lookup_enabled_rule(session, token)
    if rule is None:
        raise _denied(403, "agent_not_whitelisted", "接入未注册或未启用")
    if rule.capability != _REQUIRED_CAPABILITY:
        raise _denied(403, "agent_capability_denied", "该接入未启用 qa 能力")
    if rule.bound_user_id is None:
        raise _denied(403, "caller_unbound", "该 token 未绑定平台用户")
    caller = await gateway.resolve_caller(session, rule.bound_user_id)
    if caller is None or not caller.is_business_user:
        raise _denied(403, "caller_unresolved", "绑定用户无法解析或非业务用户")
    return rule, caller


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
    if not gateway.tool_scope_allowed(rule, req.scope):
        raise _denied(403, "agent_scope_denied", "请求范围超出该接入允许的 scope")
    if rule.allowed_project_id is not None:
        raise _denied(403, "agent_scope_denied", "项目锁定接入不支持统一检索端点")
    search_req = SearchRequest(
        query=req.query,
        scope=req.scope,
        intent=req.intent,
        filters=SearchFilters(**(req.filters or {})),
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
    )


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

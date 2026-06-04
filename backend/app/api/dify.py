"""Dify **兼容适配器** 路由（PBC-01）。

平台核心是 provider 中立的外部 Agent / 工作流网关
（`app/services/external_agent_gateway.py`）。本文件只做 **Dify 专属的线缆转译**：
把 Dify 的请求 / 响应形态映射到中立网关，权限 / 检索 / 审计 / 无泄露逻辑全部由网关核心
拥有，本适配器不持有这些业务逻辑。Dify 是临时集成面，未来 Coze / 自研工作流可新增同类适配器。

- POST /api/v1/dify/external-knowledge/retrieval：Dify External Knowledge API（官方协议）。
  Dify 侧配置端点填 `/api/v1/dify/external-knowledge`，Dify 自动追加 `/retrieval`。
- POST /api/v1/dify/tools/knowledge-search：Dify workflow HTTP Tool（返回 R3 SearchResponse）。
- GET/POST/PATCH /api/v1/admin/permissions/agent-whitelist：接入注册管理（admin，provider 中立）。

鉴权：Bearer token（注册行 token_hash 校验 + capability=qa）。调用人身份必须解析出真实平台
用户（metadata_condition.caller_user_id / X-Platform-User-Id），否则 fail closed——绝不以
admin / system / provider 自身身份检索。所有响应不含 token / token_hash / provider 内部标识 /
weknora kb·doc·chunk id / dataset·workflow·app id。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.models.agent_registry import AgentWhitelistRule
from app.schemas.dify import DifyExternalRequest, DifyToolRequest
from app.schemas.external_agent import (
    RegistryCreateRequest,
    RegistryCreateResponse,
    RegistryListResponse,
    RegistryUpdateRequest,
)
from app.schemas.permission import AccessChannel, CallerContext
from app.schemas.search import SearchFilters, SearchRequest, SearchResponse
from app.services import agent_registry
from app.services import external_agent_gateway as gateway
from app.services import search as search_service
from app.services.llm_client import get_llm_client
from app.services.weknora_client import get_weknora_client

router = APIRouter(prefix="/api/v1", tags=["dify"])

_REQUIRED_CAPABILITY = "qa"


def _bearer(authorization: str | None) -> str | None:
    """从 Authorization 头提取 Bearer token；格式非法 → None。"""
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        return None
    return parts[1].strip()


def _dify_err(status_code: int, error_code: int, error_msg: str) -> JSONResponse:
    """Dify External Knowledge API 错误格式（顶层 error_code / error_msg）。"""
    return JSONResponse(status_code=status_code, content={"error_code": error_code, "error_msg": error_msg})


def _caller_id_from(req: DifyExternalRequest, header_user_id: str | None) -> uuid.UUID | None:
    """从 metadata_condition.caller_user_id 或 X-Platform-User-Id 解析调用人 id。"""
    raw = None
    if req.metadata_condition and isinstance(req.metadata_condition, dict):
        raw = req.metadata_condition.get("caller_user_id")
    raw = raw or header_user_id
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 1) Dify External Knowledge API
# ---------------------------------------------------------------------------
@router.post("/dify/external-knowledge/retrieval")
async def dify_external_retrieval(
    req: DifyExternalRequest,
    request: Request,
    authorization: str | None = Header(default=None),
    x_platform_user_id: str | None = Header(default=None, alias="X-Platform-User-Id"),
    session: AsyncSession = Depends(get_db),
    weknora=Depends(get_weknora_client),
    llm=Depends(get_llm_client),
):
    trace_id = get_trace_id(request)
    # 鉴权：Bearer 格式 → 启用注册行 → capability。失败绝不记录 token。
    token = _bearer(authorization)
    if token is None:
        return _dify_err(403, 1001, "Invalid Authorization header format. Expected 'Bearer <api-key>' format.")
    rule = await agent_registry.lookup_enabled_rule(session, token)
    if rule is None or rule.capability != _REQUIRED_CAPABILITY:
        return _dify_err(403, 1002, "Authorization failed")

    # 调用人身份必须解析为真实平台用户，否则 fail closed（绝不以 provider/admin 身份检索）。
    caller = await gateway.resolve_caller(session, _caller_id_from(req, x_platform_user_id))
    if caller is None or not caller.is_business_user:
        return _dify_err(403, 1002, "Authorization failed: platform caller could not be resolved")

    # Dify 适配：knowledge_id → 中立知识选择器；网关返回中立 records。
    records = await gateway.run_retrieval(
        session, caller, rule,
        knowledge_selector=req.knowledge_id, query=req.query,
        top_k=req.retrieval_setting.top_k, score_threshold=req.retrieval_setting.score_threshold,
        weknora=weknora, llm=llm, trace_id=trace_id,
    )
    if records is None:
        return _dify_err(404, 2001, "The knowledge does not exist")
    # 官方响应：{records:[{content,score,title,metadata}]}。
    return {"records": [r.model_dump() for r in records]}


# ---------------------------------------------------------------------------
# 2) Dify HTTP Tool（返回 R3 SearchResponse）
# ---------------------------------------------------------------------------
async def require_qa_registry(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db),
) -> AgentWhitelistRule:
    """HTTP Tool 鉴权依赖：Bearer → 启用注册行 → capability=qa。失败 401/403（不记 token）。"""
    from fastapi import HTTPException

    token = _bearer(authorization)
    if token is None:
        raise HTTPException(401, detail={"denied_reason": "agent_unauthenticated", "message": "缺少或非法 Bearer token"})
    rule = await agent_registry.lookup_enabled_rule(session, token)
    if rule is None:
        raise HTTPException(403, detail={"denied_reason": "agent_not_whitelisted", "message": "接入未注册或未启用"})
    if rule.capability != _REQUIRED_CAPABILITY:
        raise HTTPException(403, detail={"denied_reason": "agent_capability_denied", "message": "该接入未启用 qa 能力"})
    return rule


@router.post("/dify/tools/knowledge-search", response_model=SearchResponse)
async def dify_tool_search(
    req: DifyToolRequest,
    request: Request,
    rule: AgentWhitelistRule = Depends(require_qa_registry),
    session: AsyncSession = Depends(get_db),
    weknora=Depends(get_weknora_client),
    llm=Depends(get_llm_client),
) -> SearchResponse:
    from fastapi import HTTPException

    # 调用人身份必须解析为真实平台业务用户，否则 fail closed（BE-07 §3.3：
    # Agent 调用只能由有效业务用户发起；绝不以 admin / system / provider 身份检索）。
    caller = await gateway.resolve_caller(session, req.caller_user_id)
    if caller is None or not caller.is_business_user:
        raise HTTPException(403, detail={"denied_reason": "caller_unresolved", "message": "调用人身份无法解析或非业务用户"})

    # 注册行 scope 天花板：请求 scope 与 allowed_scope 冲突 → 拒绝（绝不落回 all）。
    if not gateway.tool_scope_allowed(rule, req.scope):
        raise HTTPException(403, detail={"denied_reason": "agent_scope_denied", "message": "请求范围超出该接入允许的 scope"})
    # 项目锁定的注册行：R3 search 无法安全收口到单一项目（project scope 跨全部所在项目），
    # 故 fail closed，绝不跑更宽的 project/all 检索。
    if rule.allowed_project_id is not None:
        raise HTTPException(403, detail={"denied_reason": "agent_scope_denied", "message": "项目锁定接入请改用 external-knowledge 端点（project:<id>）"})

    search_req = SearchRequest(
        query=req.query, scope=req.scope, intent=req.intent,
        filters=SearchFilters(**req.filters.model_dump()),
        want_original=req.want_original, asset_id=req.asset_id,
    )
    # channel=agent：Agent 渠道边界（A4 原文降级等）生效。
    return await search_service.run_search(
        session, caller, search_req,
        weknora=weknora, llm=llm, trace_id=get_trace_id(request), channel=AccessChannel.agent,
    )


# ---------------------------------------------------------------------------
# 3) 接入注册管理（admin-only）——契约 §15.2 /admin/permissions/agent-whitelist
# ---------------------------------------------------------------------------
@router.get("/admin/permissions/agent-whitelist", response_model=RegistryListResponse)
async def list_agent_whitelist(
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> RegistryListResponse:
    return await agent_registry.list_rules(session, caller)


@router.post("/admin/permissions/agent-whitelist", response_model=RegistryCreateResponse)
async def create_agent_whitelist(
    req: RegistryCreateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> RegistryCreateResponse:
    return await agent_registry.create_rule(session, caller, req, get_trace_id(request))


@router.patch("/admin/permissions/agent-whitelist/{rule_id}", response_model=RegistryCreateResponse)
async def update_agent_whitelist(
    rule_id: uuid.UUID,
    req: RegistryUpdateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> RegistryCreateResponse:
    return await agent_registry.update_rule(session, caller, rule_id, req, get_trace_id(request))

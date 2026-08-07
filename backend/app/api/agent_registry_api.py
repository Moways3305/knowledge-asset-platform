"""外部 Agent 接入注册管理 API（provider 中立，admin-only）。

路由：`/admin/permissions/agent-whitelist`（list / create / patch）。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.external_agent import (
    RegistryCreateRequest,
    RegistryCreateResponse,
    RegistryListResponse,
    RegistryUpdateRequest,
)
from app.schemas.permission import CallerContext
from app.services import agent_registry

router = APIRouter(prefix="/api/v1", tags=["agent-registry"])


@router.get("/admin/permissions/agent-whitelist", response_model=RegistryListResponse)
async def list_agent_whitelist(
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> RegistryListResponse:
    result: RegistryListResponse = await agent_registry.list_rules(session, caller)
    return result


@router.post("/admin/permissions/agent-whitelist", response_model=RegistryCreateResponse)
async def create_agent_whitelist(
    req: RegistryCreateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> RegistryCreateResponse:
    result: RegistryCreateResponse = await agent_registry.create_rule(
        session, caller, req, get_trace_id(request)
    )
    return result


@router.patch("/admin/permissions/agent-whitelist/{rule_id}", response_model=RegistryCreateResponse)
async def update_agent_whitelist(
    rule_id: uuid.UUID,
    req: RegistryUpdateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> RegistryCreateResponse:
    result: RegistryCreateResponse = await agent_registry.update_rule(
        session, caller, rule_id, req, get_trace_id(request)
    )
    return result

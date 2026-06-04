"""权限规则配置中心 API（PBC-03）。

- GET   /api/v1/admin/permissions/rules           （admin / boss / 咨询总监 可读）
- PATCH /api/v1/admin/permissions/rules/{rule_id}  （仅 boss / 咨询总监；admin 只读 → 403）

权限委托 service；响应只含安全治理元数据，写动作写 config.permission_rule_updated 审计。
外部 Agent 接入注册（Agent Registry）的兼容路径 /admin/permissions/agent-whitelist 仍由
`app/api/dify.py` 提供，本路由不重复实现。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.permission import CallerContext
from app.schemas.permission_rule import (
    PermissionRuleOut,
    PermissionRulesResponse,
    PermissionRuleUpdateRequest,
)
from app.services import permission_rules as rules_service

router = APIRouter(prefix="/api/v1/admin/permissions", tags=["permissions"])


@router.get("/rules", response_model=PermissionRulesResponse)
async def list_permission_rules(
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> PermissionRulesResponse:
    return await rules_service.list_rules(session, caller)


@router.patch("/rules/{rule_id}", response_model=PermissionRuleOut)
async def update_permission_rule(
    rule_id: uuid.UUID,
    req: PermissionRuleUpdateRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> PermissionRuleOut:
    return await rules_service.update_rule(session, caller, rule_id, req, get_trace_id(request))

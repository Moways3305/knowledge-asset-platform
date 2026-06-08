"""Admin 告警设置 API。

- GET   /api/v1/admin/alerts/rules：告警规则列表（admin）。
- PATCH /api/v1/admin/alerts/rules/{rule_id}：更新规则（admin；审计 config.alert_rule_updated）。
- GET   /api/v1/admin/alerts/notifications：本地通知记录（admin）。

权限与审计委托 `app.services.alert`，本层不重写。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.alert import (
    AlertRuleOut,
    AlertRulesResponse,
    AlertRuleUpdateBody,
    NotificationsResponse,
)
from app.schemas.permission import CallerContext
from app.services import alert as alert_service

router = APIRouter(prefix="/api/v1", tags=["alert"])


@router.get("/admin/alerts/rules", response_model=AlertRulesResponse)
async def list_rules(
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> AlertRulesResponse:
    return await alert_service.list_rules(session, caller)


@router.patch("/admin/alerts/rules/{rule_id}", response_model=AlertRuleOut)
async def update_rule(
    rule_id: uuid.UUID,
    body: AlertRuleUpdateBody,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> AlertRuleOut:
    return await alert_service.update_rule(
        session, caller, rule_id, body, get_trace_id(request)
    )


@router.get("/admin/alerts/notifications", response_model=NotificationsResponse)
async def list_notifications(
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> NotificationsResponse:
    return await alert_service.list_notifications(session, caller)


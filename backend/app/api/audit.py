"""Admin Audit API（IMPLEMENT-09；契约 §18）。

- GET  /api/v1/admin/audit：审计查询（admin / boss / 咨询总监；按角色脱敏）。
- GET  /api/v1/admin/audit/trace/{trace_id}：trace 链路查询（同权限；按可见性脱敏）。
- POST /api/v1/admin/audit/{event_id}/mark-processed：标记异常已处理（仅 admin）。

权限与脱敏全部委托 `app.services.audit`，本层不重写。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.db.session import get_db
from app.schemas.audit import (
    AuditListResponse,
    AuditTraceResponse,
    MarkProcessedResponse,
)
from app.schemas.permission import CallerContext
from app.services import audit as audit_service

router = APIRouter(prefix="/api/v1", tags=["audit"])


@router.get("/admin/audit", response_model=AuditListResponse)
async def query_audit(
    log_type: str | None = Query(default=None),
    action: str | None = Query(default=None),
    actor_user_id: uuid.UUID | None = Query(default=None),
    target_type: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    is_processed: bool | None = Query(default=None),
    trace_id: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    sort_order: str = Query(default="desc"),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> AuditListResponse:
    return await audit_service.query_audit(
        session,
        caller,
        log_type=log_type,
        action=action,
        actor_user_id=actor_user_id,
        target_type=target_type,
        severity=severity,
        is_processed=is_processed,
        trace_id=trace_id,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
        sort_order=sort_order,
    )


@router.get("/admin/audit/trace/{trace_id}", response_model=AuditTraceResponse)
async def get_trace(
    trace_id: str,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> AuditTraceResponse:
    return await audit_service.get_trace(session, caller, trace_id)


@router.post(
    "/admin/audit/{event_id}/mark-processed", response_model=MarkProcessedResponse
)
async def mark_processed(
    event_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> MarkProcessedResponse:
    return await audit_service.mark_processed(session, caller, event_id)

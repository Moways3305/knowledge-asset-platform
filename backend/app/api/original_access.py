"""原文访问申请与授权 API。

- POST /api/v1/knowledge/{asset_id}/original-access/request   发起申请（业务用户，可发现该资产）
- GET  /api/v1/original-access/requests?box=mine|inbox        本人申请 / 可审批 pending 收件箱
- POST /api/v1/original-access/requests/{request_id}/approve  审批通过并生成 grant
- POST /api/v1/original-access/requests/{request_id}/reject   拒绝
- POST /api/v1/original-access/grants/{grant_id}/revoke       撤销授权

权限委托 service；响应只含安全治理元数据，写动作均写审计。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.original_access import (
    AccessGrantOut,
    CreateRequestBody,
    CreateRequestResponse,
    RequestsListResponse,
    ReviewBody,
    RevokeBody,
)
from app.schemas.permission import CallerContext
from app.services import original_access as oa_service

router = APIRouter(prefix="/api/v1", tags=["original-access"])


@router.post("/knowledge/{asset_id}/original-access/request", response_model=CreateRequestResponse)
async def create_request(
    asset_id: uuid.UUID,
    body: CreateRequestBody,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> CreateRequestResponse:
    return await oa_service.create_request(
        session, caller, asset_id, body.reason, get_trace_id(request)
    )


@router.get("/original-access/requests", response_model=RequestsListResponse)
async def list_requests(
    box: str = Query(default="mine"),
    status: str | None = Query(default=None),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> RequestsListResponse:
    return await oa_service.list_requests(session, caller, box=box, status=status)


@router.post("/original-access/requests/{request_id}/approve", response_model=CreateRequestResponse)
async def approve_request(
    request_id: uuid.UUID,
    body: ReviewBody,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> CreateRequestResponse:
    return await oa_service.approve_request(
        session, caller, request_id, body.note, get_trace_id(request)
    )


@router.post("/original-access/requests/{request_id}/reject", response_model=CreateRequestResponse)
async def reject_request(
    request_id: uuid.UUID,
    body: ReviewBody,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> CreateRequestResponse:
    return await oa_service.reject_request(
        session, caller, request_id, body.note, get_trace_id(request)
    )


@router.post("/original-access/grants/{grant_id}/revoke", response_model=AccessGrantOut)
async def revoke_grant(
    grant_id: uuid.UUID,
    body: RevokeBody,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> AccessGrantOut:
    return await oa_service.revoke_grant(
        session, caller, grant_id, body.reason, get_trace_id(request)
    )

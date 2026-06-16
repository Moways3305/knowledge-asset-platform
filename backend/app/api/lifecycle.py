"""知识生命周期动作 API。

5 个端点：archive-request / archive-confirm / reenable-request / reenable-confirm /
events。权限与状态机判断全部委托 `app.services.lifecycle`（其内部复用集中权限服务）。
trace_id 经中间件注入，统一透传进生命周期事件 / 审计 / 通知。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.lifecycle import (
    ArchiveConfirmBody,
    ArchiveConfirmResponse,
    ArchiveRequestBody,
    LifecycleActionResponse,
    LifecycleEventsResponse,
    ReenableConfirmBody,
    ReenableConfirmResponse,
    ReenableRequestBody,
)
from app.schemas.permission import CallerContext
from app.services import lifecycle as lifecycle_service

router = APIRouter(prefix="/api/v1", tags=["lifecycle"])

_PREFIX = "/knowledge/{asset_id}/lifecycle"


@router.post(f"{_PREFIX}/archive-request", response_model=LifecycleActionResponse)
async def archive_request(
    asset_id: uuid.UUID,
    body: ArchiveRequestBody,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> LifecycleActionResponse:
    return await lifecycle_service.archive_request(
        session, caller, asset_id, body, get_trace_id(request)
    )


@router.post(f"{_PREFIX}/archive-confirm", response_model=ArchiveConfirmResponse)
async def archive_confirm(
    asset_id: uuid.UUID,
    body: ArchiveConfirmBody,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ArchiveConfirmResponse:
    return await lifecycle_service.archive_confirm(
        session, caller, asset_id, body, get_trace_id(request)
    )


@router.post(f"{_PREFIX}/reenable-request", response_model=LifecycleActionResponse)
async def reenable_request(
    asset_id: uuid.UUID,
    body: ReenableRequestBody,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> LifecycleActionResponse:
    return await lifecycle_service.reenable_request(
        session, caller, asset_id, body, get_trace_id(request)
    )


@router.post(f"{_PREFIX}/reenable-confirm", response_model=ReenableConfirmResponse)
async def reenable_confirm(
    asset_id: uuid.UUID,
    body: ReenableConfirmBody,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> ReenableConfirmResponse:
    return await lifecycle_service.reenable_confirm(
        session, caller, asset_id, body, get_trace_id(request)
    )


@router.get(f"{_PREFIX}/events", response_model=LifecycleEventsResponse)
async def list_events(
    asset_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> LifecycleEventsResponse:
    return await lifecycle_service.list_events(session, caller, asset_id)

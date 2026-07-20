"""First-party business notification inbox API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.schemas.notification import (
    BusinessNotificationListResponse,
    BusinessNotificationOut,
    MarkReadBatchRequest,
    MarkReadBatchResponse,
    UnreadCountResponse,
)
from app.schemas.permission import CallerContext
from app.services import notifications as notification_service

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("", response_model=BusinessNotificationListResponse)
async def list_notifications(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    category: str | None = Query(default=None),
    unread_only: bool = Query(default=False),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> BusinessNotificationListResponse:
    return await notification_service.list_notifications(
        session,
        caller,
        page=page,
        page_size=page_size,
        category=category,
        unread_only=unread_only,
    )


@router.get("/unread-count", response_model=UnreadCountResponse)
async def unread_count(
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> UnreadCountResponse:
    return await notification_service.unread_count(session, caller)


@router.post("/{notification_id}/read", response_model=BusinessNotificationOut)
async def mark_read(
    notification_id: uuid.UUID,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> BusinessNotificationOut:
    return await notification_service.mark_read(
        session, caller, notification_id, get_trace_id(request)
    )


@router.post("/read-batch", response_model=MarkReadBatchResponse)
async def mark_read_batch(
    body: MarkReadBatchRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> MarkReadBatchResponse:
    return await notification_service.mark_read_batch(
        session, caller, body.notification_ids, get_trace_id(request)
    )

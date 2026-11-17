"""First-party business notification inbox API."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query, Request
from pydantic import AwareDatetime
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
from app.schemas.notification_inbox import (
    Category,
    InboxAction,
    InboxActionResult,
    InboxEventsResponse,
    InboxFilter,
    InboxPreferences,
    InboxResponse,
    View,
)
from app.schemas.permission import CallerContext
from app.services import notification_inbox
from app.services import notifications as notification_service
from app.services.storage import LocalFileStorage, get_storage

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


def inbox_filter(
    view: View = "inbox",
    category: Category | None = None,
    project_id: uuid.UUID | None = None,
    before: AwareDatetime | None = None,
    after: AwareDatetime | None = None,
    read_only: bool = False,
    include_archived: bool = False,
) -> InboxFilter:
    return InboxFilter(
        view=view,
        category=category,
        project_id=project_id,
        before=before,
        after=after,
        read_only=read_only,
        include_archived=include_archived,
    )


@router.get("/inbox", response_model=InboxResponse)
async def inbox(
    filters: InboxFilter = Depends(inbox_filter),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    snapshot_at: AwareDatetime | None = None,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
):
    return await notification_inbox.inbox(
        session, caller, filters, page, page_size, storage, snapshot_at
    )


@router.get("/inbox/events", response_model=InboxEventsResponse)
async def inbox_events(
    group_id: str,
    snapshot_at: AwareDatetime,
    filters: InboxFilter = Depends(inbox_filter),
    page: int = Query(default=1, ge=1),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
):
    return await notification_inbox.details(
        session, caller, group_id, filters, snapshot_at, page, storage
    )


@router.post("/inbox/actions", response_model=InboxActionResult)
async def inbox_action(
    body: InboxAction,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await notification_inbox.act(session, caller, body, get_trace_id(request))


@router.get("/preferences", response_model=InboxPreferences)
async def preferences(
    caller: CallerContext = Depends(get_caller_context), session: AsyncSession = Depends(get_db)
):
    return await notification_inbox.preferences(session, caller.user_id)


@router.put("/preferences", response_model=InboxPreferences)
async def save_preferences(
    body: InboxPreferences,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
):
    return await notification_inbox.save_preferences(session, caller, body, get_trace_id(request))


@router.get("", response_model=BusinessNotificationListResponse)
async def list_notifications(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    category: str | None = Query(default=None),
    unread_only: bool = Query(default=False),
    action_required: bool | None = Query(default=None),
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
) -> BusinessNotificationListResponse:
    return await notification_service.list_notifications(
        session,
        caller,
        page=page,
        page_size=page_size,
        category=category,
        unread_only=unread_only,
        action_required=action_required,
        storage=storage,
    )


@router.get("/unread-count", response_model=UnreadCountResponse)
async def unread_count(
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
) -> UnreadCountResponse:
    return await notification_service.unread_count(session, caller, storage=storage)


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

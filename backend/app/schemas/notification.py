"""Safe first-party business notification API schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class NotificationTarget(BaseModel):
    route_key: str
    resource_id: uuid.UUID


class BusinessNotificationOut(BaseModel):
    id: uuid.UUID
    event_type: str
    category: str
    title: str
    summary: str
    created_at: datetime
    is_read: bool
    read_at: datetime | None
    project_name: str | None = None
    object_name: str
    task_status: str
    task_group: str
    action_required: bool
    next_action_label: str
    failure_reason: str | None = None
    recovery_suggestion: str | None = None
    target: NotificationTarget


class BusinessNotificationListResponse(BaseModel):
    items: list[BusinessNotificationOut]
    total: int
    page: int
    page_size: int
    unread_count: int
    pending_count: int
    categories: list[str] = Field(default_factory=list)


class UnreadCountResponse(BaseModel):
    unread_count: int


class MarkReadBatchRequest(BaseModel):
    notification_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


class MarkReadBatchResponse(BaseModel):
    requested_count: int
    marked_count: int
    already_read_count: int

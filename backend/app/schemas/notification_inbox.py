"""Recipient-only inbox operations, with a bounded server snapshot."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from app.schemas.notification import BusinessNotificationOut

Category = Literal[
    "knowledge",
    "review",
    "ingest",
    "parsing",
    "indexing",
    "knowledge_base",
    "original_access",
    "ops",
]
View = Literal["inbox", "unread", "archived", "trash"]


class InboxFilter(BaseModel):
    view: View = "inbox"
    category: Category | None = None
    project_id: uuid.UUID | None = None
    before: AwareDatetime | None = None
    after: AwareDatetime | None = None
    read_only: bool = False
    include_archived: bool = False


class InboxAction(BaseModel):
    action: Literal["read", "unread", "seen", "archive", "delete", "restore"]
    snapshot_at: AwareDatetime
    filters: InboxFilter = Field(default_factory=InboxFilter)
    group_ids: list[str] = Field(default_factory=list, max_length=10000)
    all_matching: bool = False

    @model_validator(mode="after")
    def scope_is_explicit(self):
        if self.all_matching == bool(self.group_ids):
            raise ValueError("Select groups or all matching notifications")
        return self


class InboxGroup(BaseModel):
    id: str
    latest: BusinessNotificationOut
    event_count: int
    unread_count: int
    failed_count: int
    completed_count: int
    action_required: bool


class InboxResponse(BaseModel):
    items: list[InboxGroup]
    total: int
    unread_count: int
    unseen_count: int
    snapshot_at: datetime
    categories: list[str]
    projects: list[dict[str, str]]


class InboxActionResult(BaseModel):
    affected_count: int


class InboxEventsResponse(BaseModel):
    items: list[BusinessNotificationOut]
    total: int


class ChannelPreference(BaseModel):
    in_app: bool = True
    wecom: Literal["off", "immediate", "hourly"] = "immediate"


class InboxPreferences(BaseModel):
    categories: dict[Category, ChannelPreference] = Field(default_factory=dict)
    auto_archive_days: Literal[0, 30, 90, 180] = 0

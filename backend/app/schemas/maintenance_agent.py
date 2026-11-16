"""Explicit contracts; defaults are Beijing time, configurable per library."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ScanSettings(BaseModel):
    daily_hour: int = Field(2, ge=0, le=23)
    weekly_day: int = Field(6, ge=0, le=6)
    digest_hour: int = Field(9, ge=0, le=23)
    overdue_days: int = Field(7, ge=1, le=365)
    required_tags: list[str] = Field(default_factory=list, max_length=20)
    required_sections: list[str] = Field(default_factory=list, max_length=20)
    similarity_threshold: float = Field(0.85, ge=0.5, le=1)
    max_body_chars: int = Field(24000, ge=1000, le=60000)


class PolicyCommand(BaseModel):
    expected_revision: int = Field(0, ge=0)
    enabled: bool = False
    content_authorized: bool = False
    settings: ScanSettings = Field(default_factory=ScanSettings)


class PolicyOut(BaseModel):
    id: uuid.UUID | None = None
    library_key: str
    name: str
    enabled: bool = False
    content_authorized: bool = False
    revision: int = 0
    settings: ScanSettings = Field(default_factory=ScanSettings)
    last_error: str | None = None
    can_configure: bool = False


class RunOut(BaseModel):
    id: uuid.UUID
    policy_id: uuid.UUID
    kind: str
    status: str
    target_count: int
    completed_count: int
    incomplete_count: int
    skipped_count: int
    reasons: dict[str, int]
    started_at: datetime
    finished_at: datetime | None


class IssueOut(BaseModel):
    id: uuid.UUID
    asset_id: uuid.UUID
    title: str
    library_key: str
    rule: str
    category: str
    status: str
    suspected: bool
    first_seen_at: datetime
    last_seen_at: datetime
    updated_at: datetime
    snooze_until: datetime | None
    responsible: list[dict[str, str]]
    can_act: bool


class IssuePage(BaseModel):
    items: list[IssueOut]
    total: int
    page: int
    page_size: int


class IssueDetail(IssueOut):
    evidence: dict
    evidence_available: bool
    current_version_matches: bool
    history: list[dict]


class IssueCommand(BaseModel):
    expected_updated_at: datetime
    action: Literal["in_progress", "recheck", "snoozed", "false_positive", "resolved"]
    reason: str = Field("", max_length=1000)
    snooze_until: datetime | None = None

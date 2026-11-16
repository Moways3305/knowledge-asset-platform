"""Explicit contracts; defaults are Beijing time, configurable per library."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ScanSettings(BaseModel):
    model_ref: str = Field(default="system_default", pattern=r"^(system_default|[a-f0-9]{64})$")
    daily_hour: int = Field(default=2, ge=0, le=23)
    weekly_day: int = Field(default=6, ge=0, le=6)
    digest_hour: int = Field(default=9, ge=0, le=23)
    overdue_days: int = Field(default=7, ge=1, le=365)
    required_tags: list[str] = Field(default_factory=list, max_length=20)
    required_sections: list[str] = Field(default_factory=list, max_length=20)
    similarity_threshold: float = Field(default=0.85, ge=0.5, le=1)
    max_body_chars: int = Field(
        default=24000,
        ge=1000,
        le=60000,
        description="每批正文处理预算；长文档自动分批完成，不限制全文长度",
    )


class PolicyCommand(BaseModel):
    expected_revision: int = Field(default=0, ge=0)
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
    last_progress_at: datetime
    can_retry: bool = False


class ScopeOut(BaseModel):
    assessed_at: datetime
    visible_count: int
    target_count: int
    excluded_counts: dict[str, int]


class RunItemOut(BaseModel):
    asset_id: uuid.UUID
    title: str
    status: str
    version_id: uuid.UUID | None
    current_version_matches: bool
    coverage: dict[str, str]
    findings: dict[str, int]
    reasons: list[str]
    checked_at: datetime | None
    progress: dict[str, int] = Field(default_factory=dict)


class RunDeleteCommand(BaseModel):
    run_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


class RunDeleteResult(BaseModel):
    deleted_count: int


class RunDetail(RunOut):
    library_key: str
    historical_details_available: bool
    scope_snapshot: ScopeOut | None
    current_scope: ScopeOut
    content_authorized: bool | None
    settings: ScanSettings | None
    items: list[RunItemOut]
    total: int
    page: int
    page_size: int = 25


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
    reason: str = Field(default="", max_length=1000)
    snooze_until: datetime | None = None

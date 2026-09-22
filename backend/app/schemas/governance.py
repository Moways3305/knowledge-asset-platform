"""Company-only lifecycle workbench contracts. No original content or storage identifiers."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class GovernanceItem(BaseModel):
    asset_id: UUID
    title: str
    asset_status: str
    confidentiality_level: str
    summary: str | None
    updated_at: datetime
    archived_at: datetime | None
    archive_reason: str | None
    signals: list[str]


class GovernancePage(BaseModel):
    items: list[GovernanceItem]
    total: int
    page: int
    page_size: int
    counts: dict[str, int]


class GovernanceSelection(BaseModel):
    asset_id: UUID
    expected_status: str
    expected_updated_at: datetime


class GovernanceBatch(BaseModel):
    items: list[GovernanceSelection] = Field(min_length=1, max_length=50)
    action: Literal["archive", "restore"]
    reason_code: Literal["historical", "superseded", "duplicate", "low_value", "other"]
    reason: str = Field(min_length=1, max_length=1000)
    replacement_asset_id: UUID | None = None

    @field_validator("reason")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("reason is required")
        return value.strip()

    @field_validator("items")
    @classmethod
    def unique_ids(cls, items):
        if len({i.asset_id for i in items}) != len(items):
            raise ValueError("duplicate selections")
        return items


class GovernanceOutcome(BaseModel):
    asset_id: UUID
    success: bool
    message: str


class GovernanceBatchResult(BaseModel):
    items: list[GovernanceOutcome]

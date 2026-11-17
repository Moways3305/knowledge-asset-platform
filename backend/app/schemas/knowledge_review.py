"""Explicit, optimistic-concurrency guarded governance commands."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_updated_at: datetime
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("reason cannot be blank")
        return value.strip()


class ReviewPolicyCommand(Command):
    maintainer_user_id: uuid.UUID | None = None
    review_due_at: datetime | None = None
    review_interval_days: int | None = Field(default=None, ge=1, le=3650)
    maintenance_delegated: bool = False


class ReviewCommand(Command):
    outcome: Literal["verified", "needs_update"]
    next_review_at: datetime | None = None


class ReplacementCommand(Command):
    replacement_asset_id: uuid.UUID | None
    expected_replacement_updated_at: datetime | None = None
    confirm_archive: bool = False


class CorrectionCommand(Command):
    pass


class CorrectionTransition(Command):
    action: Literal["resolve", "verify", "reopen", "reject", "duplicate", "withdraw", "close"]


class CorrectionOut(BaseModel):
    id: uuid.UUID
    status: str
    description: str
    resolution: str | None
    updated_at: datetime
    can_resolve: bool
    can_verify: bool
    can_withdraw: bool = False
    can_reopen: bool = False
    can_close: bool = False


class ReviewState(BaseModel):
    asset_id: uuid.UUID
    updated_at: datetime
    maintainer_user_id: uuid.UUID | None
    maintainer_name: str | None
    review_due_at: datetime | None
    review_interval_days: int | None = None
    maintenance_delegated: bool = False
    can_assign: bool = False
    verified_at: datetime | None
    freshness: Literal["unreviewed", "verified", "changed", "due", "needs_update", "archived"]
    replacement_asset_id: uuid.UUID | None
    can_manage: bool
    corrections: list[CorrectionOut]
    maintainers: list[dict]


class MaintenanceItem(BaseModel):
    asset_id: uuid.UUID
    title: str
    scope: str
    review_due_at: datetime | None
    freshness: str
    needs_correction: bool
    awaiting_my_verification: bool
    agent_issue_count: int = 0
    library_key: str | None = None


class MaintenancePage(BaseModel):
    items: list[MaintenanceItem]
    total: int
    page: int
    page_size: int


class ReplacementOption(BaseModel):
    asset_id: uuid.UUID
    title: str

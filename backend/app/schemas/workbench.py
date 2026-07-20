"""First-party browser workbench response contract.

The contract is intentionally separate from Agent Gateway schemas and exposes
only first-party business identifiers and permission-filtered projections.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.knowledge_insights import (
    AccessInsights,
    InsightCard,
    LifecycleInsights,
)


class WorkbenchSectionStatus(str, Enum):
    available = "available"
    empty = "empty"
    forbidden = "forbidden"
    error = "error"


class WorkbenchTodoItem(BaseModel):
    key: str
    count: int
    severity: str
    route_key: str
    action_key: str


class WorkbenchTodosSection(BaseModel):
    status: WorkbenchSectionStatus
    error_code: str | None = None
    items: list[WorkbenchTodoItem] = Field(default_factory=list)
    total: int = 0


class WorkbenchOperationsIndexing(BaseModel):
    index_failed: int = 0
    skipped: int = 0
    not_indexed: int = 0
    parse_failed: int = 0
    parse_pending: int = 0
    parse_processing: int = 0
    kb_init_failed: int = 0


class WorkbenchOperationsSummary(BaseModel):
    title_visible: bool
    scope: str
    window_days: int
    cards: list[InsightCard] = Field(default_factory=list)
    indexing: WorkbenchOperationsIndexing
    access: AccessInsights
    lifecycle: LifecycleInsights


class WorkbenchOperationsSection(BaseModel):
    status: WorkbenchSectionStatus
    error_code: str | None = None
    data: WorkbenchOperationsSummary | None = None


class WorkbenchProjectItem(BaseModel):
    project_id: uuid.UUID
    name: str
    status: str
    project_role: str
    lifecycle_route_key: str | None = None
    lifecycle_phase_key: str | None = None


class WorkbenchProjectsSection(BaseModel):
    status: WorkbenchSectionStatus
    error_code: str | None = None
    items: list[WorkbenchProjectItem] = Field(default_factory=list)
    total: int = 0


class WorkbenchRecentActivityItem(BaseModel):
    asset_id: uuid.UUID
    title: str
    scope: str
    zone: str
    asset_type: str
    confidentiality_level: str
    summary: str | None = None
    project_name: str | None = None
    updated_at: datetime | None = None


class WorkbenchRecentActivitySection(BaseModel):
    status: WorkbenchSectionStatus
    error_code: str | None = None
    items: list[WorkbenchRecentActivityItem] = Field(default_factory=list)
    total: int = 0


class WorkbenchOverviewResponse(BaseModel):
    todos: WorkbenchTodosSection
    operations: WorkbenchOperationsSection
    projects: WorkbenchProjectsSection
    recent_activity: WorkbenchRecentActivitySection

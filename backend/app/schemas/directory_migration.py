from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DirectoryMigrationOverview(BaseModel):
    total: int
    migrated: int
    clear_match: int
    manual_required: int
    no_candidate: int
    failed: int
    rule_version: int | None


class DirectoryMigrationCandidateOut(BaseModel):
    id: uuid.UUID
    asset_title: str
    scope: str
    project_id: uuid.UUID | None
    project_name: str | None
    old_category: str | None
    suggested_directory_key: str | None
    suggested_directory_name: str | None
    candidate_source: str
    confidence: str
    status: str
    failure_code: str | None
    updated_at: datetime | None


class DirectoryMigrationWorkspaceOut(BaseModel):
    overview: DirectoryMigrationOverview
    items: list[DirectoryMigrationCandidateOut]
    total: int
    directories: list[dict]


class DirectoryMigrationConfirmItem(BaseModel):
    candidate_id: uuid.UUID
    directory_key: str | None = Field(default=None, max_length=100)


class DirectoryMigrationConfirmRequest(BaseModel):
    items: list[DirectoryMigrationConfirmItem] = Field(min_length=1, max_length=200)


class DirectoryMigrationConfirmResult(BaseModel):
    candidate_id: uuid.UUID
    status: str
    reason_code: str | None = None


class DirectoryMigrationConfirmResponse(BaseModel):
    submitted: int
    migrated: int
    skipped: int
    failed: int
    items: list[DirectoryMigrationConfirmResult]

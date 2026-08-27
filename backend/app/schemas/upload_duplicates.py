"""Safe upload-duplicate read models and explicit user decisions."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import KnowledgeScope

DuplicateState = Literal["none", "exact_content", "same_batch", "suspected_metadata"]
DuplicateMatchType = Literal[
    "none",
    "exact_content",
    "same_batch",
    "suspected_metadata",
    "restricted_match",
]


class DuplicateComparisonCandidate(BaseModel):
    """At most one permission-trimmed candidate; never carries hashes or storage ids."""

    match_type: DuplicateMatchType
    title: str | None = None
    file_name: str | None = None
    file_size: int | None = None
    scope: Literal["personal", "project", "company"] | None = None
    scope_label: str | None = None
    directory_key: str | None = None
    subject: str | None = None
    formed_on: str | None = None
    version: str | None = None
    asset_status: str | None = None
    ingested_at: datetime | None = None
    safe_summary: str | None = None
    asset_id: uuid.UUID | None = None
    can_view_detail: bool = False
    can_view_original: bool = False
    same_batch_ordinal: int | None = None


class UploadDuplicateReadModel(BaseModel):
    duplicate_state: DuplicateState = "none"
    match_type: DuplicateMatchType = "none"
    # Restricted matches deliberately omit the count to avoid existence enumeration.
    match_count: int | None = 0
    preferred_candidate: DuplicateComparisonCandidate | None = None
    same_batch_group_id: uuid.UUID | None = None
    same_batch_first_ordinal: int | None = None
    default_selected: bool = True
    decision: Literal["skip", "independent", "batch_keep"] | None = None


class DuplicateDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["skip", "independent", "keep"]
    reason: str | None = Field(default=None, max_length=300)
    target_scope: KnowledgeScope
    target_project_id: uuid.UUID | None = None


class DuplicateDecisionResponse(BaseModel):
    task_id: uuid.UUID
    status: str
    decision: Literal["skip", "independent", "batch_keep"]
    skipped_task_ids: list[uuid.UUID] = Field(default_factory=list)
    duplicate: UploadDuplicateReadModel | None = None


class MyUploadItem(BaseModel):
    task_id: uuid.UUID
    source_file_name: str
    source_file_size: int | None = None
    uploaded_at: datetime
    target_scope: str | None = None
    target_project_id: uuid.UUID | None = None
    target_project_name: str | None = None
    processing_status: str
    final_status: Literal[
        "processing",
        "awaiting_confirmation",
        "waiting_review",
        "completed",
        "failed",
        "duplicate_skipped",
    ]
    duplicate_result: Literal["none", "skipped", "independent"] = "none"
    result_asset_id: uuid.UUID | None = None


class MyUploadListResponse(BaseModel):
    items: list[MyUploadItem]
    total: int

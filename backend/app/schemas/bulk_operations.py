"""Safe, terminal contracts shared by controlled bulk operations."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, model_validator

BulkItemStatus = Literal["succeeded", "skipped", "failed"]
BulkExecutionMode = Literal["synchronous", "controlled_batch"]


class BulkItemResult(BaseModel):
    item_id: uuid.UUID
    status: BulkItemStatus
    reason_code: str | None = None
    message: str | None = None


class BulkOperationResponse(BaseModel):
    operation_id: uuid.UUID
    status: Literal["completed", "completed_with_errors"]
    execution_mode: BulkExecutionMode
    submitted: int
    succeeded: int
    skipped: int
    failed: int
    items: list[BulkItemResult]


class BulkRequestContext(BaseModel):
    """Optional transport metadata that correlates bounded client requests."""

    client_operation_id: uuid.UUID | None = None
    request_index: int | None = Field(default=None, ge=1)
    request_count: int | None = Field(default=None, ge=1)
    total_submitted: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_request_context(self) -> BulkRequestContext:
        values = (
            self.client_operation_id,
            self.request_index,
            self.request_count,
            self.total_submitted,
        )
        if any(value is not None for value in values) and any(value is None for value in values):
            raise ValueError("bulk request context must be provided as a complete set")
        if self.request_index is not None and self.request_count is not None:
            if self.request_index > self.request_count:
                raise ValueError("request_index must not exceed request_count")
        item_count = len(getattr(self, "item_ids", getattr(self, "items", ())))
        if self.total_submitted is not None and self.total_submitted < item_count:
            raise ValueError("total_submitted must cover the current request")
        return self


class BulkIdsRequest(BulkRequestContext):
    item_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def reject_duplicate_ids(self) -> BulkIdsRequest:
        if len(set(self.item_ids)) != len(self.item_ids):
            raise ValueError("item_ids must not contain duplicates")
        return self


class ReviewBulkActionRequest(BulkIdsRequest):
    action: Literal["approve", "reject"]
    review_comment: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def require_reject_reason(self) -> ReviewBulkActionRequest:
        if self.action == "reject" and not (self.review_comment or "").strip():
            raise ValueError("review_comment is required when rejecting")
        return self


class OriginalAccessBulkActionRequest(BulkIdsRequest):
    action: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=500)


class PersonalSubmitBulkRequest(BulkIdsRequest):
    target_project_id: uuid.UUID
    note: str | None = Field(default=None, max_length=500)


class KnowledgeBulkDeleteRequest(BulkIdsRequest):
    scope: Literal["personal", "project"]
    project_id: uuid.UUID | None = None
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def require_project_for_project_scope(self) -> KnowledgeBulkDeleteRequest:
        if self.scope == "project" and self.project_id is None:
            raise ValueError("project_id is required for project scope")
        if self.scope == "personal" and self.project_id is not None:
            raise ValueError("project_id is not valid for personal scope")
        return self

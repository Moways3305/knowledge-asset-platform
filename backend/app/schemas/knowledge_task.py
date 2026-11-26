import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.personal_information import redact_personal_information


class TaskCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    instruction: str = Field(min_length=2, max_length=600)

    @field_validator("instruction")
    @classmethod
    def sanitize(cls, value):
        value = redact_personal_information(value.strip())
        if len(value) < 2:
            raise ValueError("请输入资料名称或用途")
        return value[:600]


class TaskRow(BaseModel):
    id: uuid.UUID
    instruction: str
    status: Literal["queued", "searching", "checking", "ready", "empty", "failed"]
    created_at: datetime


class SourceLink(BaseModel):
    asset_id: uuid.UUID
    title: str


class TaskEvidence(BaseModel):
    asset_id: uuid.UUID
    version_id: uuid.UUID
    title: str
    version: str
    summary: str | None
    original: bool
    matched: list[str]
    summary_matched: list[str]
    unmatched: list[str]
    old_source_links: list[SourceLink]
    needs_update: bool
    pending_update: bool
    parsed: bool
    correction_status: str | None
    history_truncated: bool
    compared_version: str | None
    changed_fields: list[str]
    previous_summary: str | None
    current_summary: str | None
    updated_at: datetime


class TaskDetail(TaskRow):
    failure_reason: Literal["access_changed", "tool_error"] | None = None
    mode: str | None = None
    candidates: int = 0
    inspected: int = 0
    evidence: TaskEvidence | None = None
    availability: Literal["available", "changed", "unavailable"] | None = None

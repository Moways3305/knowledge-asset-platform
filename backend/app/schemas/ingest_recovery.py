"""Safe schemas for historical processing-timeout recovery operations."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProcessingTimeoutRecoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = True
    confirm: bool = False
    limit: int = Field(default=3, ge=1, le=3)
    expected_oom_kill_count: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def execution_requires_confirmation(self) -> ProcessingTimeoutRecoveryRequest:
        if not self.dry_run and not self.confirm:
            raise ValueError("actual recovery requires confirm=true")
        return self


class ProcessingTimeoutPreflight(BaseModel):
    redis_ready: bool
    ocr_worker_ready: bool
    queue_within_budget: bool
    oom_kill_count: int
    ready: bool
    reason: str | None = None


class ProcessingTimeoutRecoveryResponse(BaseModel):
    dry_run: bool
    scanned: int
    candidates: int
    source_unavailable: int
    selected: int
    claimed: int
    enqueued: int
    conflicts: int
    stopped: bool
    stop_reason: str | None = None
    preflight: ProcessingTimeoutPreflight
    next_batch_not_before: datetime | None = None

"""Explicit upload-session item state machine and aggregate facts."""

from __future__ import annotations

from app.models.ingest import IngestTask
from app.schemas.enums import IngestStatus

TERMINAL_ITEM_STATES = frozenset(
    {"awaiting_confirmation", "completed", "duplicate_skipped", "failed", "cancelled"}
)
COMPLETED_ITEM_STATES = frozenset(
    {"awaiting_confirmation", "completed", "duplicate_skipped", "cancelled"}
)


def task_item_state(task: IngestTask) -> str:
    if task.status == IngestStatus.cancelled.value or task.cancel_requested:
        return "cancelled"
    if task.status == IngestStatus.pending_confirmation.value:
        return "awaiting_confirmation"
    if task.status == IngestStatus.duplicate_skipped.value:
        return "duplicate_skipped"
    if task.status in {
        IngestStatus.completed.value,
        IngestStatus.waiting_review.value,
        IngestStatus.rejected.value,
    }:
        return "completed"
    if task.status == IngestStatus.failed.value:
        return "failed"
    if task.status == IngestStatus.pending.value and task.processing_stage == "upload_waiting":
        return "waiting"
    return "processing"

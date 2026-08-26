"""Explicit upload-session item state machine and aggregate facts."""

from __future__ import annotations

from app.models.ingest import IngestTask
from app.schemas.enums import IngestStatus

TERMINAL_ITEM_STATES = frozenset({"awaiting_confirmation", "completed", "failed", "cancelled"})
COMPLETED_ITEM_STATES = frozenset({"awaiting_confirmation", "completed", "cancelled"})


def task_item_state(task: IngestTask) -> str:
    if task.status == IngestStatus.pending_confirmation.value:
        return "awaiting_confirmation"
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


def session_status(item_states: list[str], *, upload_completed: bool) -> str:
    if upload_completed and all(state in TERMINAL_ITEM_STATES for state in item_states):
        return "completed"
    return "active"

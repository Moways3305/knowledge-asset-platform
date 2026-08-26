"""Pure, explicit and idempotent review state transitions."""

from __future__ import annotations

from datetime import datetime

from app.models.review import ReviewTask
from app.schemas.enums import ReviewTaskStatus

TERMINAL_REVIEW_STATES = {
    ReviewTaskStatus.approved.value,
    ReviewTaskStatus.rejected.value,
}


class ReviewTransitionConflict(ValueError):
    pass


def decide(
    task: ReviewTask,
    *,
    target_status: str,
    comment: str | None,
    decided_at: datetime,
    allowed_from: set[str] | None = None,
) -> bool:
    """Apply one terminal decision; an identical replay is a no-op."""
    if target_status not in TERMINAL_REVIEW_STATES:
        raise ReviewTransitionConflict("target status is not terminal")
    if task.status == target_status:
        return False
    if task.status in TERMINAL_REVIEW_STATES:
        raise ReviewTransitionConflict("review already finalized with another decision")
    if allowed_from is not None and task.status not in allowed_from:
        raise ReviewTransitionConflict("review state does not allow this decision")
    task.status = target_status
    task.review_comment = comment
    task.reviewed_at = decided_at
    return True

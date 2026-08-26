from datetime import datetime, timezone

import pytest

from app.models.review import ReviewTask
from app.services.review_transitions import ReviewTransitionConflict, decide


def _task(status: str = "pending_reviewer") -> ReviewTask:
    return ReviewTask(review_type="material_to_asset", trigger_source="test", status=status)


def test_review_decision_is_explicit_and_idempotent():
    task = _task()
    now = datetime.now(timezone.utc)
    assert decide(task, target_status="approved", comment="ok", decided_at=now) is True
    assert task.status == "approved"
    assert decide(task, target_status="approved", comment="ignored", decided_at=now) is False
    assert task.review_comment == "ok"


def test_review_decision_rejects_conflicting_terminal_replay():
    task = _task("approved")
    with pytest.raises(ReviewTransitionConflict, match="another decision"):
        decide(
            task,
            target_status="rejected",
            comment="no",
            decided_at=datetime.now(timezone.utc),
        )

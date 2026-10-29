import pytest
from test_user_notifications import API, _headers, _row

from app.models.review import ReviewTask
from app.seed.dev_seed import REVIEW_SEED, USER_CONSULTANT, USER_PROJECT_MANAGER


@pytest.mark.parametrize("outcome", ["rejected", "cancelled", "approved"])
async def test_review_notifications_keep_terminal_business_outcome(client, db_session, outcome):
    task = await db_session.get(ReviewTask, REVIEW_SEED)
    task.status = outcome
    pending = _row(recipient=USER_PROJECT_MANAGER)
    decided = _row(recipient=USER_CONSULTANT, dedup_key="terminal-result")
    decided.event_type = "review.decided"
    db_session.add_all([pending, decided])
    await db_session.commit()
    for user in [USER_PROJECT_MANAGER, USER_CONSULTANT]:
        response = await client.get(API, headers=_headers(user))
        assert response.status_code == 200
        row = response.json()["items"][0]
        assert row["task_status"] == ("completed" if outcome == "approved" else outcome)
        assert row["action_required"] is False
        assert row["task_group"] == "recent_completed"
        assert response.json()["pending_count"] == 0

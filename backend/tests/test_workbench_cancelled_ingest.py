"""Cancellation outranks an older review rejection in every upload read model."""

import pytest

from app.models.ingest import IngestTask
from app.models.review import ReviewTask
from app.schemas.permission import CallerContext
from app.seed.dev_seed import PROJECT_ALPHA, USER_CONSULTANT
from app.services import ingest, workbench
from app.services.upload_duplicates import my_upload_projection


@pytest.mark.parametrize(
    "task_status,cancel_requested,review_status,rejected_count",
    [
        ("cancelled", False, "rejected", 0),
        ("cancelled", False, "cancelled", 0),
        ("cancelled", False, "pending_reviewer", 0),
        ("waiting_review", True, "rejected", 0),
        ("waiting_review", False, "rejected", 1),
        ("failed", False, "rejected", 1),
    ],
)
async def test_cancelled_upload_has_no_ghost_rejected_todo(
    db_session, task_status, cancel_requested, review_status, rejected_count
):
    task = IngestTask(
        source="path_b_upload",
        source_file_ref="synthetic://cancelled-upload",
        source_file_name="synthetic-cancelled.txt",
        status=task_status,
        cancel_requested=cancel_requested,
        created_by=USER_CONSULTANT,
    )
    db_session.add(task)
    await db_session.flush()
    review = ReviewTask(
        review_type="project_ingest_approval",
        trigger_source="synthetic",
        source_ingest_task_id=task.id,
        status=review_status,
        submitted_by=USER_CONSULTANT,
    )
    db_session.add(review)
    await db_session.commit()
    caller = CallerContext(
        user_id=USER_CONSULTANT,
        is_active=True,
        active_company_roles={"consultant"},
        active_project_ids={PROJECT_ALPHA},
    )

    todos = await workbench.build_todos(db_session, caller, shared={"reviews": []})
    counts = {item.key: item.count for item in todos.items}
    assert counts.get("ingest_rejected", 0) == rejected_count
    assert counts.get("ingest_pending", 0) == 0
    assert counts.get("ingest_failed", 0) == 0

    pending = await ingest.list_pending(db_session, caller, include_duplicates=False)
    own_pending = [item for item in pending if item.id == task.id]
    assert bool(own_pending) is bool(rejected_count)
    projection = my_upload_projection(task, review=review)
    assert projection.final_status == ("rejected" if rejected_count else "cancelled")

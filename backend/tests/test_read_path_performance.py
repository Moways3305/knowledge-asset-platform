"""Query budgets for production read paths, including authorization and chunk boundaries."""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import event

from app.models.ingest import IngestTask, UploadSession, UploadSessionItem
from app.models.notification import BusinessNotification
from app.schemas.permission import CallerContext
from app.seed.dev_seed import USER_CONSULTANT, USER_PROJECT_MANAGER
from app.services.ingest import list_pending
from app.services.notifications import list_notifications
from app.services.storage import LocalFileStorage
from app.services.upload_session_projection import build_response


def caller():
    return CallerContext(
        user_id=USER_CONSULTANT,
        is_active=True,
        active_company_roles={"consultant"},
        active_project_ids=set(),
    )


@contextmanager
def queries(db):
    statements = []
    engine = db.bind.sync_engine

    def capture(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", capture)


@pytest.mark.parametrize("count", [10, 100, 201])
async def test_upload_poll_and_pending_query_budgets(db_session, tmp_path, count):
    value = UploadSession(
        created_by=USER_CONSULTANT,
        total_files=count,
        total_batches=1,
        target_scope="personal",
        items=[],
    )
    tasks = [
        IngestTask(
            source="path_b_upload",
            source_file_ref="missing/ref",
            source_file_name=f"file-{i}.txt",
            source_file_hash=f"{i:064x}",
            status="pending_confirmation",
            target_scope="personal",
            created_by=USER_CONSULTANT,
        )
        for i in range(count)
    ]
    db_session.add_all([value, *tasks])
    await db_session.flush()
    value.items = [
        UploadSessionItem(
            ingest_task_id=task.id,
            ordinal=i,
            batch_index=0,
            file_name=task.source_file_name,
            file_size=1,
            status="awaiting_confirmation",
        )
        for i, task in enumerate(tasks)
    ]
    await db_session.commit()
    chunks = (count + 99) // 100
    with queries(db_session) as sql:
        result = await build_response(
            db_session, caller(), value, storage=LocalFileStorage(tmp_path)
        )
    assert len(result.items) == count
    assert len(sql) <= 1 + 4 * chunks
    assert all(item.duplicate.duplicate_state == "none" for item in result.items)
    with queries(db_session) as sql:
        result = await list_pending(db_session, caller())
    assert len(result) == count
    assert len(sql) <= 2 + 4 * chunks


async def test_notification_pagination_crosses_hidden_rows_with_bounded_queries(db_session):
    tasks = [
        IngestTask(
            source="path_b_upload",
            source_file_ref="test/ref",
            source_file_name="task.txt",
            status="failed",
            created_by=USER_CONSULTANT if i % 2 else USER_PROJECT_MANAGER,
        )
        for i in range(421)
    ]
    db_session.add_all(tasks)
    await db_session.flush()
    rows = [
        BusinessNotification(
            recipient_user_id=USER_CONSULTANT,
            event_type="ingest.failed",
            category="ingest",
            title="Task",
            summary="Safe summary",
            target_kind="ingest_task",
            target_id=task.id,
            dedup_key=str(uuid.uuid4()),
            channel="in_app",
            delivery_status="pending",
        )
        for task in tasks
    ]
    db_session.add_all(rows)
    await db_session.commit()
    visible_ids = {
        row.id for row, task in zip(rows, tasks, strict=True) if task.created_by == USER_CONSULTANT
    }
    with queries(db_session) as sql:
        first = await list_notifications(
            db_session, caller(), page=1, page_size=20, category=None, unread_only=False
        )
    assert len(sql) <= 6  # Three chunks, one notification and one task query each.
    second = await list_notifications(
        db_session, caller(), page=2, page_size=20, category="ingest", unread_only=True
    )
    assert first.total == second.total == 210
    assert first.unread_count == first.pending_count == 210
    assert len(first.items) == len(second.items) == 20
    first_ids = {item.id for item in first.items}
    second_ids = {item.id for item in second.items}
    assert not first_ids & second_ids
    assert first_ids | second_ids <= visible_ids


async def test_personal_batch_preview_isolates_foreign_tasks(client, db_session):
    own = IngestTask(
        source="path_b_upload",
        source_file_ref="test/ref",
        source_file_name="own.txt",
        status="pending_confirmation",
        target_scope="personal",
        created_by=USER_CONSULTANT,
    )
    foreign = IngestTask(
        source="path_b_upload",
        source_file_ref="test/ref",
        source_file_name="foreign.txt",
        status="pending_confirmation",
        target_scope="personal",
        created_by=USER_PROJECT_MANAGER,
    )
    db_session.add_all([own, foreign])
    await db_session.commit()
    result = await client.post(
        "/api/v1/ingest/bulk-naming-preview",
        headers={"X-Dev-User-Id": str(USER_CONSULTANT)},
        json={
            "target_scope": "personal",
            "items": [
                {"task_id": str(task.id), "confidentiality_level": "L2"} for task in [own, foreign]
            ],
        },
    )
    assert result.status_code == 200, result.text
    first, second = result.json()["items"]
    assert first["submittable"] and first["duplicate"]["duplicate_state"] == "none"
    assert second["error_code"] == "item_unavailable" and not second["submittable"]

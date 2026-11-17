"""Inbox lifecycle does not mutate business state or consume later arrivals."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select, update
from test_user_notifications import _headers, _row

from app.db.utils import utc_now
from app.models.identity import ProjectMember, User
from app.models.ingest import IngestTask, UploadSession, UploadSessionItem
from app.models.notification import BusinessNotification as N
from app.models.review import ReviewTask
from app.seed.dev_seed import PROJECT_ALPHA, REVIEW_SEED, USER_CONSULTANT, USER_PROJECT_MANAGER
from app.services import notification_digest, notifications

API = "/api/v1/notifications"
HEADERS = _headers(USER_PROJECT_MANAGER)


async def listing(client, **params):
    response = await client.get(f"{API}/inbox", params=params, headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


async def action(client, snapshot, name, *, view="inbox", filters=None, groups=None):
    response = await client.post(
        f"{API}/inbox/actions",
        headers=HEADERS,
        json={
            "action": name,
            "snapshot_at": snapshot,
            "filters": filters or {"view": view},
            **({"group_ids": groups} if groups else {"all_matching": True}),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["affected_count"]


async def test_clear_thousands_cross_pages_preserves_new_arrivals_and_business(client, db_session):
    old = utc_now() - timedelta(days=90)
    rows = [_row(dedup_key=f"history-{i}") for i in range(1205)]
    for row in rows:
        row.created_at = old
    foreign = _row(recipient=USER_CONSULTANT)
    db_session.add_all([*rows, foreign])
    await db_session.commit()
    task = await db_session.get(ReviewTask, REVIEW_SEED)
    status = task.status
    before = await listing(client)
    assert before["total"] == before["unread_count"] == before["unseen_count"] == 1
    assert before["items"][0]["event_count"] == 1205
    new = _row(dedup_key="arrived-after-snapshot")
    db_session.add(new)
    await db_session.commit()
    assert await action(client, before["snapshot_at"], "delete") == 1205
    assert await action(client, before["snapshot_at"], "delete") == 0
    remaining = await listing(client)
    assert remaining["items"][0]["event_count"] == 1
    assert remaining["unseen_count"] == 1
    assert (await listing(client, view="trash"))["items"][0]["event_count"] == 1205
    assert await action(client, remaining["snapshot_at"], "restore", view="trash") == 1205
    restored = await listing(client)
    assert restored["items"][0]["event_count"] == 1206
    await db_session.refresh(foreign)
    await db_session.refresh(task)
    assert foreign.deleted_at is None
    assert task.status == status
    assert await db_session.scalar(select(func.count()).select_from(N)) == 1207


async def test_seen_read_archive_restore_are_independent(client, db_session):
    db_session.add(_row())
    await db_session.commit()
    initial = await listing(client)
    await action(client, initial["snapshot_at"], "seen")
    seen = await listing(client)
    assert (seen["unseen_count"], seen["unread_count"]) == (0, 1)
    assert seen["items"][0]["action_required"]
    await action(client, seen["snapshot_at"], "read")
    read = await listing(client)
    assert read["unread_count"] == 0
    assert read["items"][0]["action_required"]
    await action(client, read["snapshot_at"], "unread")
    unread = await listing(client)
    assert (unread["unseen_count"], unread["unread_count"]) == (0, 1)
    await action(client, unread["snapshot_at"], "archive")
    assert (await listing(client))["total"] == 0
    assert (await listing(client, view="archived"))["total"] == 1
    await action(client, unread["snapshot_at"], "restore", view="archived")
    assert (await listing(client))["unseen_count"] == 0


async def test_filters_selection_cutoff_and_archive_read(client, db_session):
    early, late, read = [_row(dedup_key=str(i)) for i in range(3)]
    early.created_at = utc_now() - timedelta(days=60)
    late.created_at = read.created_at = utc_now() - timedelta(days=1)
    read.read_at = utc_now()
    db_session.add_all([early, late, read])
    await db_session.commit()
    state = await listing(client)
    assert await action(client, state["snapshot_at"], "archive", filters={"read_only": True}) == 1
    assert await action(client, state["snapshot_at"], "delete", groups=["foreign-group"]) == 0
    assert (
        await action(
            client,
            state["snapshot_at"],
            "delete",
            filters={"before": (utc_now() - timedelta(days=30)).isoformat()},
        )
        == 1
    )
    assert (await listing(client))["items"][0]["event_count"] == 1
    assert (await listing(client, category="ingest"))["total"] == 0


async def test_revoked_target_hides_group_details_counters_but_history_can_be_cleared(
    client, db_session
):
    row = _row()
    db_session.add(row)
    await db_session.commit()
    state = await listing(client)
    await db_session.execute(
        update(ProjectMember)
        .where(
            ProjectMember.project_id == PROJECT_ALPHA, ProjectMember.user_id == USER_PROJECT_MANAGER
        )
        .values(status="inactive")
    )
    await db_session.commit()
    hidden = await listing(client)
    assert hidden["total"] == hidden["unseen_count"] == hidden["unread_count"] == 0
    response = await client.get(
        f"{API}/inbox/events",
        headers=HEADERS,
        params={"group_id": state["items"][0]["id"], "snapshot_at": state["snapshot_at"]},
    )
    assert response.status_code == 404
    assert await action(client, state["snapshot_at"], "delete") == 1


async def test_batch_upload_groups_only_authorized_members_and_paginates_events(client, db_session):
    batch = UploadSession(created_by=USER_PROJECT_MANAGER, total_files=25, total_batches=1)
    db_session.add(batch)
    await db_session.flush()
    for index in range(25):
        task = IngestTask(
            source="path_b_upload",
            source_file_ref="internal://test",
            source_file_name=f"{index}.txt",
            status="failed",
            created_by=USER_PROJECT_MANAGER,
        )
        db_session.add(task)
        await db_session.flush()
        db_session.add(
            UploadSessionItem(
                session_id=batch.id,
                ingest_task_id=task.id,
                ordinal=index,
                batch_index=0,
                file_name=f"{index}.txt",
                file_size=10,
            )
        )
        db_session.add(
            N(
                recipient_user_id=USER_PROJECT_MANAGER,
                event_type="ingest.failed",
                category="ingest",
                title="入库处理未完成",
                summary="请查看结果",
                target_kind="ingest_task",
                target_id=task.id,
                dedup_key=f"task-{index}",
            )
        )
    await db_session.commit()
    state = await listing(client)
    assert state["total"] == 1
    group = state["items"][0]
    assert group["event_count"] == group["failed_count"] == 25
    response = await client.get(
        f"{API}/inbox/events",
        headers=HEADERS,
        params={"group_id": group["id"], "snapshot_at": state["snapshot_at"], "page": 2},
    )
    assert response.status_code == 200
    assert len(response.json()["items"]) == 5


async def test_preferences_persist_and_delivery_uses_durable_hourly_summary(
    client, db_session, monkeypatch
):
    user = await db_session.get(User, USER_PROJECT_MANAGER)
    user.wecom_user_id = "test-manager"
    await db_session.commit()
    body = {"categories": {"review": {"in_app": True, "wecom": "hourly"}}, "auto_archive_days": 30}
    response = await client.put(f"{API}/preferences", headers=HEADERS, json=body)
    assert response.status_code == 200, response.text
    assert (await client.get(f"{API}/preferences", headers=HEADERS)).json() == body
    monkeypatch.setattr(
        "app.services.wecom_notification.default_notification_channel", lambda: "wecom"
    )
    for index in range(3):
        await notifications._record(
            db_session,
            recipients=[USER_PROJECT_MANAGER],
            event_type="review.project_pending",
            target_kind="review",
            target_id=REVIEW_SEED,
            project_id=PROJECT_ALPHA,
            dedup_key=f"digest-{index}",
        )
    await db_session.commit()
    rows = list(await db_session.scalars(select(N)))
    assert len(rows) == 3
    assert {row.channel for row in rows} == {"digest_pending"}
    await notification_digest.bundle_due(db_session)
    assert await db_session.scalar(select(func.count()).select_from(N)) == 3
    await db_session.execute(
        update(N).values(delivery_available_at=utc_now() - timedelta(seconds=1))
    )
    await db_session.commit()
    await notification_digest.bundle_due(db_session)
    await notification_digest.bundle_due(db_session)
    envelopes = list(
        await db_session.scalars(select(N).where(N.target_kind == "notification_digest"))
    )
    assert len(envelopes) == 1
    from app.services.notification_delivery import Message

    prepared = await notifications._prepare_delivery(db_session, envelopes[0])
    assert isinstance(prepared, Message), prepared
    assert "1 项业务" in prepared.content
    assert (await listing(client))["items"][0]["event_count"] == 3
    # Revoking the channel also suppresses queued envelopes, not just new messages.
    body["categories"]["review"]["wecom"] = "off"
    await client.put(f"{API}/preferences", headers=HEADERS, json=body)
    assert (
        await notifications._prepare_delivery(db_session, envelopes[0])
    ).code == "notifications_disabled"


async def test_auto_archive_only_finished_read_history_and_restore_resets_window(
    client, db_session
):
    pending = _row()
    pending.read_at = utc_now() - timedelta(days=50)
    db_session.add(pending)
    task = IngestTask(
        source="path_b_upload",
        source_file_ref="internal://test",
        source_file_name="complete.txt",
        status="cancelled",
        created_by=USER_PROJECT_MANAGER,
    )
    db_session.add(task)
    await db_session.flush()
    done = N(
        recipient_user_id=USER_PROJECT_MANAGER,
        event_type="ingest.confirmed",
        category="ingest",
        title="已结束的入库",
        summary="已结束",
        target_kind="ingest_task",
        target_id=task.id,
        dedup_key="old-finished",
        read_at=utc_now() - timedelta(days=50),
    )
    db_session.add(done)
    await db_session.commit()
    await client.put(f"{API}/preferences", headers=HEADERS, json={"auto_archive_days": 30})
    state = await listing(client)
    assert state["total"] == 1
    assert state["items"][0]["action_required"]
    archive = await listing(client, view="archived")
    assert archive["total"] == 1
    await action(client, archive["snapshot_at"], "restore", view="archived")
    assert (await listing(client))["total"] == 2


async def test_disabled_in_app_is_applied_only_to_new_messages(client, db_session, monkeypatch):
    db_session.add(_row(dedup_key="old"))
    await db_session.commit()
    await client.put(
        f"{API}/preferences",
        headers=HEADERS,
        json={"categories": {"review": {"in_app": False, "wecom": "off"}}},
    )
    monkeypatch.setattr(
        "app.services.wecom_notification.default_notification_channel", lambda: "wecom"
    )
    await notifications._record(
        db_session,
        recipients=[USER_PROJECT_MANAGER],
        event_type="review.project_pending",
        target_kind="review",
        target_id=REVIEW_SEED,
        project_id=PROJECT_ALPHA,
        dedup_key="new-disabled",
    )
    await db_session.commit()
    state = await listing(client)
    assert state["items"][0]["event_count"] == 1
    row = await db_session.scalar(select(N).where(N.dedup_key == "new-disabled"))
    assert row.channel == "in_app" and not row.in_app_enabled


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "delete", "snapshot_at": "2026-01-01T00:00:00Z"},
        {
            "action": "delete",
            "snapshot_at": "2026-01-01T00:00:00Z",
            "all_matching": True,
            "group_ids": ["a"],
        },
        {"action": "delete", "snapshot_at": "2026-01-01", "all_matching": True},
    ],
)
async def test_bulk_requires_explicit_scope_and_timezone(client, payload):
    response = await client.post(f"{API}/inbox/actions", headers=HEADERS, json=payload)
    assert response.status_code == 422

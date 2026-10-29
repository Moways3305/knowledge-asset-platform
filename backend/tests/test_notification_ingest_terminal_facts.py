"""Notification targets use review outcomes without reviving old timeout retries."""

import pytest
from test_read_path_performance import queries

from app.models.ingest import IngestTask
from app.models.notification import BusinessNotification
from app.models.review import ReviewTask
from app.schemas.permission import CallerContext
from app.seed.dev_seed import KA_COMPANY_L2, USER_CONSULTANT, USER_PROJECT_MANAGER
from app.services import notification_targets


def caller():
    return CallerContext(
        user_id=USER_CONSULTANT,
        is_active=True,
        active_company_roles={"consultant"},
        active_project_ids=set(),
    )


async def fixture(
    session,
    *,
    task_status="failed",
    review_status="rejected",
    owner=USER_CONSULTANT,
    result_asset_id=None,
):
    task = IngestTask(
        source="path_b_upload",
        source_file_ref="synthetic://old-timeout",
        source_file_name="synthetic-old-timeout.txt",
        status=task_status,
        error_type="processing_timeout",
        created_by=owner,
        result_asset_id=result_asset_id,
    )
    session.add(task)
    await session.flush()
    session.add(
        ReviewTask(
            review_type="project_ingest_approval",
            trigger_source="synthetic",
            source_ingest_task_id=task.id,
            status=review_status,
            submitted_by=owner,
            confirmation_snapshot={"title": "do not load private review snapshot"},
        )
    )
    notice = BusinessNotification(
        recipient_user_id=USER_CONSULTANT,
        event_type="ingest.failed",
        category="ingest",
        title="入库处理未完成",
        summary="一项入库任务需要处理。",
        target_kind="ingest_task",
        target_id=task.id,
        dedup_key=f"synthetic-terminal:{task.id}",
        channel="in_app",
    )
    session.add(notice)
    await session.flush()
    return task, notice


@pytest.mark.parametrize("task_status", ["waiting_review", "failed"])
@pytest.mark.parametrize("review_status", ["rejected", "cancelled"])
async def test_legacy_review_terminal_overrides_timeout_in_notification_api(
    client, db_session, task_status, review_status
):
    task, notice = await fixture(db_session, task_status=task_status, review_status=review_status)
    await db_session.commit()
    response = await client.get(
        "/api/v1/notifications", headers={"X-Dev-User-Id": str(USER_CONSULTANT)}
    )
    assert response.status_code == 200
    body = response.json()
    item = next(value for value in body["items"] if value["id"] == str(notice.id))
    assert item["target"]["resource_id"] == str(task.id)
    assert item["task_status"] == review_status
    assert item["task_group"] == "recent_completed"
    assert item["action_required"] is False
    assert item["is_read"] is False and item["read_at"] is None
    assert body["pending_count"] == 0 and body["unread_count"] == 1
    assert item["next_action_label"] == "查看记录"
    assert "超时" not in (item["failure_reason"] or "")
    assert "重试" not in (item["recovery_suggestion"] or "")
    if review_status == "rejected":
        assert "未通过审核" in item["failure_reason"]
        assert "重新上传" in item["recovery_suggestion"]
    else:
        assert item["failure_reason"] is None and item["recovery_suggestion"] is None
    assert "synthetic://" not in response.text


class NeverInspectStorage:
    def inspect(self, _ref):
        raise AssertionError("a terminal task must not inspect old timeout source bytes")


@pytest.mark.parametrize("review_status", ["rejected", "cancelled"])
async def test_unbatched_notification_resolution_uses_terminal_review_before_storage(
    db_session, review_status
):
    _, notice = await fixture(db_session, review_status=review_status)
    await db_session.commit()
    visible = await notification_targets.resolve(
        db_session, caller(), notice, storage=NeverInspectStorage()
    )
    assert visible.status == review_status and visible.action_required is False


async def test_batch_review_facts_add_no_queries_or_unauthorized_targets(db_session):
    notices = []
    for index in range(40):
        _, notice = await fixture(
            db_session,
            owner=USER_CONSULTANT if index % 2 else USER_PROJECT_MANAGER,
            review_status="rejected" if index % 3 else "cancelled",
        )
        notices.append(notice)
    await db_session.commit()
    with queries(db_session) as statements:
        facts = await notification_targets.preload_targets(db_session, notices)
        visible = [
            await notification_targets.resolve(
                db_session, caller(), notice, facts=facts, storage=NeverInspectStorage()
            )
            for notice in notices
        ]
    assert len(statements) == 1
    assert "confirmation_snapshot" not in statements[0]
    assert "review_comment" not in statements[0]
    assert sum(target is not None for target in visible) == 20
    assert all(target is None or not target.action_required for target in visible)


async def test_formed_asset_is_not_reclassified_by_a_historical_rejected_review(db_session):
    _, notice = await fixture(db_session, task_status="completed", result_asset_id=KA_COMPANY_L2)
    await db_session.commit()
    visible = await notification_targets.resolve(
        db_session, caller(), notice, storage=NeverInspectStorage()
    )
    assert visible.status == "completed" and visible.action_required is False
    assert visible.failure_reason is None and visible.recovery_suggestion is None

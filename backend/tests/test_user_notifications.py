"""PBC-72 business notification inbox authorization and delivery tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.models.audit import AuditEvent
from app.models.identity import ProjectMember, User
from app.models.indexing_job import IndexingOperationJob
from app.models.ingest import IngestTask
from app.models.notification import BusinessNotification
from app.models.original_access import OriginalAccessRequest
from app.models.review import CompanyAssetReviewDecision, ReviewTask
from app.schemas.enums import ReviewTaskStatus, ReviewType
from app.seed.dev_seed import (
    PROJECT_ALPHA,
    REVIEW_SEED,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
    USER_PROJECT_MANAGER,
)
from app.services.notifications import (
    dispatch_pending,
    notify_operation_job_finished,
    notify_original_access_pending,
    notify_review_pending,
)
from app.services.wecom_client import WeComError

API = "/api/v1/notifications"


def _headers(user_id: uuid.UUID) -> dict[str, str]:
    return {"X-Dev-User-Id": str(user_id)}


def _row(
    *,
    recipient: uuid.UUID = USER_PROJECT_MANAGER,
    target_id: uuid.UUID = REVIEW_SEED,
    dedup_key: str | None = None,
    project_id: uuid.UUID | None = PROJECT_ALPHA,
    channel: str = "in_app",
) -> BusinessNotification:
    return BusinessNotification(
        recipient_user_id=recipient,
        event_type="review.project_pending",
        category="review",
        title="项目事项待确认",
        summary="有一项项目事项等待你确认。",
        target_kind="review",
        target_id=target_id,
        project_id=project_id,
        dedup_key=dedup_key or f"review.project_pending:{target_id}",
        channel=channel,
        delivery_status="pending",
    )


async def test_project_review_delivery_only_targets_active_project_manager(db_session):
    task = await db_session.get(ReviewTask, REVIEW_SEED)
    await notify_review_pending(db_session, task)
    await db_session.commit()

    recipients = set(
        (
            await db_session.execute(
                select(BusinessNotification.recipient_user_id).where(
                    BusinessNotification.target_id == REVIEW_SEED
                )
            )
        )
        .scalars()
        .all()
    )
    assert recipients == {USER_PROJECT_MANAGER}
    assert USER_BOSS not in recipients
    assert USER_DIRECTOR not in recipients
    assert USER_ADMIN_ONLY not in recipients


async def test_processing_timeout_notification_uses_retryable_safe_copy(client, db_session):
    source_ref = client._kap_storage.save(b"recoverable", original_name="timeout.txt")
    task = IngestTask(
        source="path_b_upload",
        source_file_ref=source_ref,
        source_file_name="timeout.txt",
        status="failed",
        error_type="processing_timeout",
        created_by=USER_CONSULTANT,
    )
    db_session.add(task)
    await db_session.flush()
    db_session.add(
        BusinessNotification(
            recipient_user_id=USER_CONSULTANT,
            event_type="ingest.failed",
            category="ingest",
            title="入库处理未完成",
            summary="你提交的一项入库任务需要处理。",
            target_kind="ingest_task",
            target_id=task.id,
            dedup_key=f"ingest.failed:{task.id}",
            channel="in_app",
            delivery_status="pending",
        )
    )
    await db_session.commit()

    response = await client.get(API, headers=_headers(USER_CONSULTANT))
    item = next(
        value
        for value in response.json()["items"]
        if value["target"]["resource_id"] == str(task.id)
    )
    assert item["failure_reason"] == "处理超时，文件仍可重试"
    assert item["next_action_label"] == "重试处理"
    assert item["recovery_suggestion"] == "打开上传页使用“重试处理”；若无法操作请联系管理员。"
    assert "internal://" not in response.text


async def test_processing_timeout_notification_requires_reupload_when_source_is_missing(
    client, db_session
):
    task = IngestTask(
        source="path_b_upload",
        source_file_ref=f"internal://{uuid.uuid4().hex}/missing.txt",
        source_file_name="missing.txt",
        status="failed",
        error_type="processing_timeout",
        created_by=USER_CONSULTANT,
    )
    db_session.add(task)
    await db_session.flush()
    db_session.add(
        BusinessNotification(
            recipient_user_id=USER_CONSULTANT,
            event_type="ingest.failed",
            category="ingest",
            title="入库处理未完成",
            summary="你提交的一项入库任务需要处理。",
            target_kind="ingest_task",
            target_id=task.id,
            dedup_key=f"ingest.failed:{task.id}",
            channel="in_app",
            delivery_status="pending",
        )
    )
    await db_session.commit()

    response = await client.get(API, headers=_headers(USER_CONSULTANT))
    item = next(
        value
        for value in response.json()["items"]
        if value["target"]["resource_id"] == str(task.id)
    )
    assert item["failure_reason"] == "源文件不可用，请重新上传"
    assert item["next_action_label"] == "重新上传"
    assert item["recovery_suggestion"] == "请重新选择原文件上传。"


async def test_company_confirmation_maps_only_to_active_governance_roles(db_session):
    task = ReviewTask(
        review_type=ReviewType.project_to_company.value,
        trigger_source="test",
        target_project_id=PROJECT_ALPHA,
        target_scope="company",
        status=ReviewTaskStatus.pending_reviewer.value,
        submitted_by=USER_PROJECT_MANAGER,
    )
    db_session.add(task)
    await db_session.flush()
    await notify_review_pending(db_session, task)
    await db_session.commit()

    recipients = set(
        (
            await db_session.execute(
                select(BusinessNotification.recipient_user_id).where(
                    BusinessNotification.target_id == task.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert recipients == {USER_BOSS, USER_DIRECTOR}


async def test_confirmed_company_seat_is_history_not_current_users_todo(client, db_session):
    task = ReviewTask(
        review_type="project_to_company",
        trigger_source="test",
        target_project_id=PROJECT_ALPHA,
        target_scope="company",
        status="pending_reviewer",
        submitted_by=USER_PROJECT_MANAGER,
    )
    db_session.add(task)
    await db_session.flush()
    await notify_review_pending(db_session, task)
    db_session.add(
        CompanyAssetReviewDecision(
            review_task_id=task.id,
            required_role="boss",
            decision="confirmed",
            actor_user_id=USER_BOSS,
        )
    )
    await db_session.commit()
    for user, expected in [(USER_BOSS, False), (USER_DIRECTOR, True)]:
        response = await client.get(API, headers=_headers(user))
        assert response.status_code == 200
        item = next(
            row for row in response.json()["items"] if row["target"]["resource_id"] == str(task.id)
        )
        assert item["action_required"] is expected
        assert item["task_group"] == ("my_tasks" if expected else "running_jobs")
        assert response.json()["pending_count"] == int(expected)

    decision = await db_session.scalar(
        select(CompanyAssetReviewDecision).where(
            CompanyAssetReviewDecision.review_task_id == task.id
        )
    )
    decision.decision = "withdrawn"
    await db_session.commit()
    reopened = await client.get(API, headers=_headers(USER_BOSS))
    assert reopened.status_code == 200
    assert reopened.json()["pending_count"] == 1
    assert reopened.json()["items"][0]["action_required"]


async def test_confirmed_company_seat_cancels_stale_external_delivery(db_session):
    task = ReviewTask(
        review_type="project_to_company",
        trigger_source="test",
        target_project_id=PROJECT_ALPHA,
        target_scope="company",
        status="pending_reviewer",
        submitted_by=USER_PROJECT_MANAGER,
    )
    db_session.add(task)
    await db_session.flush()
    db_session.add(
        CompanyAssetReviewDecision(
            review_task_id=task.id,
            required_role="boss",
            decision="confirmed",
            actor_user_id=USER_BOSS,
        )
    )
    notification = _row(recipient=USER_BOSS, target_id=task.id, channel="wecom")
    notification.event_type = "review.company_confirmation_pending"
    db_session.add(notification)
    await db_session.commit()

    class NeverSend:
        async def send(self, **kwargs):
            raise AssertionError("Confirmed seats must not receive stale pending messages")

    result = await dispatch_pending(db_session, sender=NeverSend())
    assert result["expired"] == 1
    assert result["sent"] == 0


def test_dual_role_user_cannot_fill_both_company_seats_in_read_projection():
    from app.schemas.permission import CallerContext
    from app.services.company_confirmation_policy import select_confirmation_role
    from app.services.review_support import _company_can_decide

    caller = CallerContext(
        user_id=USER_BOSS,
        is_active=True,
        active_company_roles={"boss", "consulting_director"},
        active_project_ids=set(),
    )
    states = {
        "boss": CompanyAssetReviewDecision(
            required_role="boss", decision="confirmed", actor_user_id=USER_BOSS
        )
    }
    assert select_confirmation_role(caller, states) is None
    assert not _company_can_decide(caller, ReviewTask(status="pending_reviewer"), states)


async def test_original_access_project_notification_does_not_fan_out_by_company_role(db_session):
    request = OriginalAccessRequest(
        asset_id=uuid.UUID("00000000-0000-0000-0000-0000000000e8"),
        requester_user_id=USER_CONSULTANT,
        project_id=PROJECT_ALPHA,
        status="pending",
    )
    db_session.add(request)
    await db_session.flush()
    await notify_original_access_pending(db_session, request)
    await db_session.commit()

    recipients = set(
        (
            await db_session.execute(
                select(BusinessNotification.recipient_user_id).where(
                    BusinessNotification.target_id == request.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert recipients == {USER_PROJECT_MANAGER}


async def test_list_paginates_and_response_is_sensitive_field_whitelist(client, db_session):
    for index in range(3):
        db_session.add(_row(dedup_key=f"page:{index}"))
    await db_session.commit()

    response = await client.get(
        API, params={"page": 2, "page_size": 2}, headers=_headers(USER_PROJECT_MANAGER)
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 1
    assert set(body["items"][0]) == {
        "id",
        "event_type",
        "category",
        "title",
        "summary",
        "created_at",
        "is_read",
        "read_at",
        "project_name",
        "object_name",
        "task_status",
        "task_group",
        "action_required",
        "next_action_label",
        "failure_reason",
        "recovery_suggestion",
        "target",
    }
    serialized = response.text.lower()
    for forbidden in (
        "recipient_user_id",
        "project_id",
        "storage_ref",
        "source_file_ref",
        "weknora",
        "fetch_token",
        "api_key",
    ):
        assert forbidden not in serialized


async def test_action_filter_precedes_pagination_and_uses_live_authorized_status(
    client, db_session
):
    completed = ReviewTask(
        review_type="personal_to_project",
        trigger_source="test",
        target_project_id=PROJECT_ALPHA,
        target_scope="project",
        status="approved",
        submitted_by=USER_CONSULTANT,
    )
    db_session.add(completed)
    await db_session.flush()
    base = datetime(2026, 8, 1, tzinfo=timezone.utc)
    pending_rows = []
    for index in range(3):
        row = _row(dedup_key=f"older-pending:{index}")
        row.created_at = base + timedelta(minutes=index)
        pending_rows.append(row)
        db_session.add(row)
    for index in range(21):
        row = _row(target_id=completed.id, dedup_key=f"newer-update:{index}")
        row.created_at = base + timedelta(days=1, minutes=index)
        db_session.add(row)
    # Neither an inaccessible target nor another recipient may affect the filtered counts.
    db_session.add(_row(target_id=uuid.uuid4(), dedup_key="missing-target"))
    db_session.add(_row(recipient=USER_CONSULTANT, dedup_key="other-recipient"))
    pending_rows[0].read_at = base + timedelta(hours=1)
    await db_session.commit()

    headers = _headers(USER_PROJECT_MANAGER)
    unfiltered = (await client.get(API, headers=headers)).json()
    assert len(unfiltered["items"]) == 20
    assert all(not item["action_required"] for item in unfiltered["items"])
    assert unfiltered["pending_count"] == 3

    first = await client.get(
        API, params={"action_required": "true", "page_size": 2}, headers=headers
    )
    assert first.status_code == 200
    body = first.json()
    assert body["total"] == body["pending_count"] == 3
    assert body["unread_count"] == 23
    assert [item["id"] for item in body["items"]] == [
        str(pending_rows[2].id),
        str(pending_rows[1].id),
    ]
    second = (
        await client.get(
            API, params={"action_required": "true", "page_size": 2, "page": 2}, headers=headers
        )
    ).json()
    assert [item["id"] for item in second["items"]] == [str(pending_rows[0].id)]
    assert second["items"][0]["is_read"] is True

    updates = (
        await client.get(
            API, params={"action_required": "false", "page_size": 20, "page": 2}, headers=headers
        )
    ).json()
    assert updates["total"] == 21
    assert len(updates["items"]) == 1
    assert updates["pending_count"] == 3
    assert not updates["items"][0]["action_required"]
    unread = (
        await client.get(
            API,
            params={"action_required": "true", "unread_only": "true", "category": "review"},
            headers=headers,
        )
    ).json()
    assert unread["total"] == 2
    assert unread["pending_count"] == 3

    task = await db_session.get(ReviewTask, REVIEW_SEED)
    task.status = "approved"
    await db_session.commit()
    refreshed = (await client.get(API, params={"action_required": "true"}, headers=headers)).json()
    assert refreshed["items"] == []
    assert refreshed["total"] == refreshed["pending_count"] == 0
    assert refreshed["unread_count"] == 23
    history = (await client.get(API, params={"action_required": "false"}, headers=headers)).json()
    assert history["total"] == 24


async def test_notification_action_filter_rejects_invalid_values(client):
    response = await client.get(
        API, params={"action_required": "unknown"}, headers=_headers(USER_PROJECT_MANAGER)
    )
    assert response.status_code == 422


async def test_read_is_idempotent_and_audited_once(client, db_session):
    row = _row()
    db_session.add(row)
    await db_session.commit()

    first = await client.post(f"{API}/{row.id}/read", headers=_headers(USER_PROJECT_MANAGER))
    second = await client.post(f"{API}/{row.id}/read", headers=_headers(USER_PROJECT_MANAGER))
    count = (
        await db_session.execute(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.action == "notification.read",
                AuditEvent.target_id == row.id,
            )
        )
    ).scalar_one()

    assert first.status_code == second.status_code == 200
    first_read_at = datetime.fromisoformat(first.json()["read_at"].replace("Z", "+00:00"))
    second_read_at = datetime.fromisoformat(second.json()["read_at"].replace("Z", "+00:00"))
    assert first_read_at.replace(tzinfo=None) == second_read_at.replace(tzinfo=None)
    assert count == 1
    assert (
        await client.get(f"{API}/unread-count", headers=_headers(USER_PROJECT_MANAGER))
    ).json() == {"unread_count": 0}


async def test_batch_read_deduplicates_ids_and_is_idempotent(client, db_session):
    first = _row(dedup_key="batch:1")
    second = _row(dedup_key="batch:2")
    db_session.add_all([first, second])
    await db_session.commit()

    response = await client.post(
        f"{API}/read-batch",
        json={"notification_ids": [str(first.id), str(first.id), str(second.id)]},
        headers=_headers(USER_PROJECT_MANAGER),
    )
    again = await client.post(
        f"{API}/read-batch",
        json={"notification_ids": [str(first.id), str(second.id)]},
        headers=_headers(USER_PROJECT_MANAGER),
    )
    assert response.json() == {
        "requested_count": 2,
        "marked_count": 2,
        "already_read_count": 0,
    }
    assert again.json() == {
        "requested_count": 2,
        "marked_count": 0,
        "already_read_count": 2,
    }


async def test_finished_operation_job_is_deduplicated_and_projects_safe_status(client, db_session):
    job = IndexingOperationJob(
        operation_type="kb_migrate",
        status="completed_with_errors",
        requested_by_user_id=USER_ADMIN_ONLY,
        scope_filter={},
    )
    db_session.add(job)
    await db_session.flush()
    await notify_operation_job_finished(db_session, job)
    await notify_operation_job_finished(db_session, job)
    await db_session.commit()

    body = (await client.get(API, headers=_headers(USER_ADMIN_ONLY))).json()
    assert body["total"] == 1
    assert body["unread_count"] == 1
    assert body["categories"] == ["knowledge_base"]
    assert body["items"][0]["task_status"] == "partial"
    assert body["items"][0]["task_group"] == "attention_items"
    assert body["items"][0]["target"]["route_key"] == "models"


async def test_submitted_index_job_notifies_pending_confirmation_instead_of_completion(
    client, db_session
):
    job = IndexingOperationJob(
        operation_type="retry_index",
        status="submitted_pending_index",
        requested_by_user_id=USER_ADMIN_ONLY,
        total_count=2,
        success_count=0,
        failed_count=0,
        skipped_count=0,
        scope_filter={"scope": "all"},
    )
    db_session.add(job)
    await db_session.flush()
    await notify_operation_job_finished(db_session, job)
    await notify_operation_job_finished(db_session, job)
    await db_session.commit()

    body = (await client.get(API, headers=_headers(USER_ADMIN_ONLY))).json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["task_status"] == "submitted"
    assert "已提交" in item["title"]
    assert "已完成" not in item["title"]
    assert "对账确认" in str(item)


async def test_duplicate_skipped_ingest_projects_a_distinct_terminal_notification_status(
    client, db_session
):
    task = IngestTask(
        source="path_b_upload",
        source_file_ref="server-only/duplicate-notification.txt",
        source_file_name="duplicate-notification.txt",
        status="duplicate_skipped",
        created_by=USER_CONSULTANT,
    )
    db_session.add(task)
    await db_session.flush()
    db_session.add(
        BusinessNotification(
            recipient_user_id=USER_CONSULTANT,
            event_type="ingest.confirmed",
            category="ingest",
            title="入库状态已更新",
            summary="资料处理已结束。",
            target_kind="ingest_task",
            target_id=task.id,
            project_id=None,
            dedup_key=f"ingest.confirmed:{task.id}",
            channel="in_app",
            delivery_status="pending",
        )
    )
    await db_session.commit()

    body = (await client.get(API, headers=_headers(USER_CONSULTANT))).json()
    assert body["total"] == 1
    assert body["items"][0]["task_status"] == "duplicate_skipped"
    assert body["items"][0]["task_group"] == "recent_completed"
    assert body["items"][0]["action_required"] is False
    assert "server-only" not in str(body)


@pytest.mark.parametrize("status", ["cancelled", "processing", "failed"])
async def test_cancelled_ingest_notification_is_an_explicit_terminal_state(
    client, db_session, status
):
    task = IngestTask(
        source="path_b_upload",
        source_file_ref="server-only/cancelled-notification.txt",
        source_file_name="cancelled-notification.txt",
        status=status,
        cancel_requested=True,
        error_type="processing_timeout",
        created_by=USER_CONSULTANT,
    )
    db_session.add(task)
    await db_session.flush()
    db_session.add(
        BusinessNotification(
            recipient_user_id=USER_CONSULTANT,
            event_type="ingest.failed",
            category="ingest",
            title="入库状态已更新",
            summary="资料处理已结束。",
            target_kind="ingest_task",
            target_id=task.id,
            dedup_key=f"ingest.cancelled:{task.id}",
            channel="in_app",
            delivery_status="pending",
        )
    )
    await db_session.commit()

    body = (await client.get(API, headers=_headers(USER_CONSULTANT))).json()
    item = next(value for value in body["items"] if value["target"]["resource_id"] == str(task.id))
    assert item["task_status"] == "cancelled"
    assert item["task_group"] == "recent_completed"
    assert item["action_required"] is False
    assert item["failure_reason"] is None
    assert item["recovery_suggestion"] is None
    assert item["next_action_label"] == "查看记录"


async def test_cancelled_review_notification_is_not_actionable(client, db_session):
    task = ReviewTask(
        review_type=ReviewType.project_ingest_approval.value,
        trigger_source="path_b_upload",
        target_project_id=PROJECT_ALPHA,
        target_scope="project",
        status=ReviewTaskStatus.cancelled.value,
        reviewer_user_id=USER_PROJECT_MANAGER,
        submitted_by=USER_CONSULTANT,
        reviewed_at=datetime.now(timezone.utc),
    )
    db_session.add(task)
    await db_session.flush()
    db_session.add(_row(target_id=task.id, dedup_key=f"review.cancelled:{task.id}"))
    await db_session.commit()

    body = (await client.get(API, headers=_headers(USER_PROJECT_MANAGER))).json()
    item = next(value for value in body["items"] if value["target"]["resource_id"] == str(task.id))
    assert item["task_status"] == "cancelled"
    assert item["task_group"] == "recent_completed"
    assert item["action_required"] is False


async def test_project_scoped_operation_notification_uses_ops_authorization_not_membership(
    client, db_session
):
    job = IndexingOperationJob(
        operation_type="retry_index",
        status="completed",
        requested_by_user_id=USER_ADMIN_ONLY,
        scope_filter={"project_id": str(PROJECT_ALPHA)},
    )
    db_session.add(job)
    await db_session.flush()
    await notify_operation_job_finished(db_session, job)
    await db_session.commit()

    # USER_ADMIN_ONLY deliberately has no PROJECT_ALPHA membership. The project id is an
    # operation filter, while visibility remains guarded by requester ownership / ops role.
    body = (await client.get(API, headers=_headers(USER_ADMIN_ONLY))).json()
    assert body["total"] == 1
    assert body["items"][0]["category"] == "indexing"
    assert body["items"][0]["task_status"] == "completed"
    assert body["items"][0]["target"]["route_key"] == "admin_ingest"


async def test_membership_removal_hides_but_terminal_target_keeps_history(client, db_session):
    row = _row()
    db_session.add(row)
    await db_session.commit()
    assert (await client.get(API, headers=_headers(USER_PROJECT_MANAGER))).json()["total"] == 1

    membership = (
        await db_session.execute(
            select(ProjectMember).where(
                ProjectMember.user_id == USER_PROJECT_MANAGER,
                ProjectMember.project_id == PROJECT_ALPHA,
            )
        )
    ).scalar_one()
    membership.status = "inactive"
    await db_session.commit()
    hidden = await client.get(API, headers=_headers(USER_PROJECT_MANAGER))
    assert hidden.json()["total"] == 0
    assert (
        await client.post(f"{API}/{row.id}/read", headers=_headers(USER_PROJECT_MANAGER))
    ).status_code == 404

    membership.status = "active"
    task = await db_session.get(ReviewTask, REVIEW_SEED)
    task.status = "approved"
    await db_session.commit()
    terminal = (await client.get(API, headers=_headers(USER_PROJECT_MANAGER))).json()
    assert terminal["total"] == 1
    assert terminal["items"][0]["task_status"] == "completed"
    assert terminal["items"][0]["action_required"] is False


async def test_non_reviewer_and_pure_admin_cannot_observe_business_notification(client, db_session):
    db_session.add_all(
        [
            _row(recipient=USER_CONSULTANT, dedup_key="consultant-copy"),
            _row(recipient=USER_ADMIN_ONLY, dedup_key="admin-copy"),
        ]
    )
    await db_session.commit()

    consultant = await client.get(API, headers=_headers(USER_CONSULTANT))
    admin = await client.get(API, headers=_headers(USER_ADMIN_ONLY))
    assert consultant.json()["total"] == 0
    assert admin.json()["total"] == 0
    assert admin.json()["items"] == []


class _FlakySender:
    def __init__(self) -> None:
        self.calls = 0

    async def send(self, **_kwargs) -> None:
        self.calls += 1
        if self.calls == 1:
            raise WeComError("SECRET-LIKE upstream payload", "raw secret message")


async def test_delivery_failure_retries_with_safe_audit_and_revalidates_target(db_session):
    user = await db_session.get(User, USER_PROJECT_MANAGER)
    user.wecom_user_id = "safe-recipient"
    row = _row(channel="wecom")
    db_session.add(row)
    await db_session.commit()
    sender = _FlakySender()

    failed = await dispatch_pending(db_session, sender=sender, trace_id="trace-secret-test")
    sent = await dispatch_pending(db_session, sender=sender, trace_id="trace-secret-test")
    await db_session.refresh(row)
    audits = list(
        (
            await db_session.execute(
                select(AuditEvent)
                .where(AuditEvent.target_id == row.id)
                .order_by(AuditEvent.created_at)
            )
        )
        .scalars()
        .all()
    )

    assert failed == {"processed": 1, "sent": 0, "failed": 1, "expired": 0}
    assert sent == {"processed": 1, "sent": 1, "failed": 0, "expired": 0}
    assert row.delivery_attempts == 2
    assert row.failure_code is None
    assert [event.action for event in audits] == [
        "notification.business_delivery_failed",
        "notification.business_delivered",
    ]
    serialized = " ".join(str(event.extra) for event in audits)
    assert "SECRET-LIKE" not in serialized
    assert "safe-recipient" not in serialized


async def test_expired_delivery_target_is_not_sent_or_retried(db_session):
    user = await db_session.get(User, USER_PROJECT_MANAGER)
    user.wecom_user_id = "safe-recipient"
    task = await db_session.get(ReviewTask, REVIEW_SEED)
    task.status = "approved"
    row = _row(channel="wecom")
    db_session.add(row)
    await db_session.commit()
    sender = _FlakySender()

    result = await dispatch_pending(db_session, sender=sender, trace_id="expired-target")
    again = await dispatch_pending(db_session, sender=sender, trace_id="expired-target")
    await db_session.refresh(row)

    assert result == {"processed": 1, "sent": 0, "failed": 0, "expired": 1}
    assert again == {"processed": 0, "sent": 0, "failed": 0, "expired": 0}
    assert sender.calls == 0
    assert row.delivery_attempts == 3
    assert row.failure_code == "target_unavailable"

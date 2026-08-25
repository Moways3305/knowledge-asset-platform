"""PBC-72 business notification inbox authorization and delivery tests."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select

from app.models.audit import AuditEvent
from app.models.identity import ProjectMember, User
from app.models.indexing_job import IndexingOperationJob
from app.models.notification import BusinessNotification
from app.models.original_access import OriginalAccessRequest
from app.models.review import ReviewTask
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

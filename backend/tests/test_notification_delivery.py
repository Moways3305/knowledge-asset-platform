"""Delivery policy, deadlines and safe retry semantics shared by both channels."""

import asyncio
import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from app.db.utils import utc_now
from app.models.audit import AuditEvent
from app.models.identity import User
from app.models.ingest import IngestTask
from app.models.lifecycle import NotificationRecord
from app.models.notification import BusinessNotification
from app.seed.dev_seed import USER_BOSS, USER_CONSULTANT
from app.services import notification_delivery as delivery
from app.services import notifications, wecom_notification
from app.services.wecom_client import WeComError


@pytest.fixture(params=["business", "ops"])
def kind(request):
    return request.param


def model(kind):
    return BusinessNotification if kind == "business" else NotificationRecord


def status(row):
    return row.delivery_status if isinstance(row, BusinessNotification) else row.send_status


def attempts(row):
    return row.delivery_attempts if isinstance(row, BusinessNotification) else row.send_attempts


def failure(row):
    return row.failure_code if isinstance(row, BusinessNotification) else row.failure_reason


async def seed(session, kind, count=1):
    user = await session.get(User, USER_CONSULTANT)
    user.wecom_user_id = "synthetic-recipient"
    ids = []
    for _ in range(count):
        common = dict(
            id=uuid.uuid4(),
            recipient_user_id=USER_CONSULTANT,
            channel="wecom",
            title="Synthetic notice",
        )
        if kind == "business":
            task = IngestTask(
                id=uuid.uuid4(),
                source="path_b_upload",
                status="failed",
                created_by=USER_CONSULTANT,
                source_file_ref="synthetic",
                source_file_name="synthetic.txt",
            )
            session.add(task)
            await session.flush()
            row = BusinessNotification(
                **common,
                summary="Safe synthetic summary",
                event_type="ingest.failed",
                category="ingest",
                target_kind="ingest_task",
                target_id=task.id,
                dedup_key=uuid.uuid4().hex,
            )
        else:
            row = NotificationRecord(**common, content="Safe synthetic summary")
        session.add(row)
        ids.append(row.id)
    await session.commit()
    return ids


async def dispatch(session, kind, sender, **kwargs):
    service = notifications if kind == "business" else wecom_notification
    return await service.dispatch_pending(session, sender=sender, **kwargs)


class Sender:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    async def send(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error


async def test_disabled_keeps_pending_and_attempts(db_session, kind):
    (row_id,) = await seed(db_session, kind)
    result = await dispatch(db_session, kind, wecom_notification.NullWeComNotificationSender())
    row = await db_session.get(model(kind), row_id)
    assert result["processed"] == 0
    assert status(row) == "pending" and attempts(row) == 0 and row.delivery_token is None


async def test_retry_has_backoff_and_revalidates_recipient(db_session, kind):
    (row_id,) = await seed(db_session, kind)
    sender = Sender(WeComError("secret-error-payload", "secret-message"))
    result = await dispatch(db_session, kind, sender)
    assert result["failed"] == 1 and len(sender.calls) == 1
    assert (await dispatch(db_session, kind, sender))["processed"] == 0
    row = await db_session.get(model(kind), row_id)
    assert failure(row) == "delivery_failed" and attempts(row) == 1
    row.delivery_available_at = utc_now() - timedelta(seconds=1)
    user = await db_session.get(User, USER_CONSULTANT)
    user.status = "inactive"
    await db_session.commit()
    assert (await dispatch(db_session, kind, Sender()))["failed"] == 1
    await db_session.refresh(row)
    assert failure(row) == "recipient_unavailable" and attempts(row) == 2
    audit = list(await db_session.scalars(select(AuditEvent).where(AuditEvent.target_id == row_id)))
    assert len(audit) == 2
    assert "secret" not in str([entry.extra for entry in audit])


async def test_timeout_is_unknown_and_batch_does_not_claim_tail(db_session, kind, monkeypatch):
    ids = await seed(db_session, kind, 3)
    monkeypatch.setattr(delivery, "BATCH_SECONDS", 0.15)
    monkeypatch.setattr(delivery, "SEND_TIMEOUT_SECONDS", 1)
    calls = []

    class Slow:
        async def send(self, **kwargs):
            calls.append(1)
            await asyncio.sleep(5)

    result = await asyncio.wait_for(dispatch(db_session, kind, Slow()), 2)
    rows = list(await db_session.scalars(select(model(kind)).where(model(kind).id.in_(ids))))
    assert result["processed"] == result["failed"] == 1 and len(calls) == 1
    assert sorted(attempts(row) for row in rows) == [0, 0, 1]
    assert [failure(row) for row in rows if attempts(row)] == ["delivery_outcome_unknown"]
    assert all(row.delivery_token is None for row in rows)


async def test_exhausted_abandoned_claim_gets_terminal_result(db_session, kind):
    (row_id,) = await seed(db_session, kind)
    row = await db_session.get(model(kind), row_id)
    setattr(row, "delivery_attempts" if kind == "business" else "send_attempts", 3)
    row.delivery_token = str(uuid.uuid4())
    row.delivery_until = utc_now() - timedelta(seconds=1)
    await db_session.commit()
    sender = Sender()
    assert (await dispatch(db_session, kind, sender))["failed"] == 1
    await db_session.refresh(row)
    assert status(row) == "failed" and attempts(row) == 3
    assert failure(row) == "delivery_outcome_unknown" and row.delivery_token is None
    assert not sender.calls
    assert (await dispatch(db_session, kind, sender))["processed"] == 0


async def test_committed_success_survives_later_sender_failure(db_session, kind):
    ids = await seed(db_session, kind, 2)
    sender = Sender()
    assert (await dispatch(db_session, kind, sender, limit=1))["sent"] == 1
    failing = Sender(WeComError("wecom_network_error", "synthetic"))
    assert (await dispatch(db_session, kind, failing))["failed"] == 1
    rows = list(await db_session.scalars(select(model(kind)).where(model(kind).id.in_(ids))))
    assert sorted(status(row) for row in rows) == ["failed", "sent"]
    assert all(attempts(row) == 1 for row in rows)


async def test_pending_caller_changes_are_not_committed(db_session, kind):
    await seed(db_session, kind)
    user = await db_session.get(User, USER_CONSULTANT)
    user.name = "Uncommitted edit"
    with pytest.raises(ValueError, match="requires_committed"):
        await dispatch(db_session, kind, Sender())
    assert user in db_session.dirty


async def test_retry_rechecks_business_target_ownership(db_session):
    (row_id,) = await seed(db_session, "business")
    await dispatch(db_session, "business", Sender(WeComError("wecom_network_error", "test")))
    row = await db_session.get(BusinessNotification, row_id)
    task = await db_session.get(IngestTask, row.target_id)
    task.created_by = USER_BOSS
    row.delivery_available_at = utc_now() - timedelta(seconds=1)
    await db_session.commit()
    sender = Sender()
    result = await dispatch(db_session, "business", sender)
    await db_session.refresh(row)
    assert result["expired"] == 1 and row.delivery_attempts == 3
    assert row.failure_code == "target_unavailable" and not sender.calls


@pytest.mark.parametrize("mode", ["timeout", "http_error", "missing_code", "rejected", "success"])
async def test_sender_requires_confirmed_provider_success(monkeypatch, mode):
    async def respond(request):
        if request.url.path.endswith("gettoken"):
            return httpx.Response(200, json={"access_token": "synthetic"})
        if mode == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        if mode == "http_error":
            return httpx.Response(503, json={"errcode": 0})
        if mode == "missing_code":
            return httpx.Response(200, json={"unexpected": "synthetic"})
        return httpx.Response(200, json={"errcode": 40003 if mode == "rejected" else 0})

    client_class = httpx.AsyncClient
    monkeypatch.setattr(
        wecom_notification.httpx,
        "AsyncClient",
        lambda **kwargs: client_class(**kwargs, transport=httpx.MockTransport(respond)),
    )
    sender = wecom_notification.WeComNotificationSender(
        corp_id="synthetic", agent_id="1", app_secret="synthetic", base_url="http://fixture"
    )
    if mode == "success":
        await sender.send(wecom_user_id="synthetic", title="synthetic", content="synthetic")
    else:
        with pytest.raises(WeComError) as exc:
            await sender.send(wecom_user_id="synthetic", title="synthetic", content="synthetic")
        assert exc.value.code == (
            "wecom_msg_40003" if mode == "rejected" else "delivery_outcome_unknown"
        )

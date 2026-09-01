"""Controlled recovery of terminal historical processing timeouts."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.audit import AuditEvent
from app.models.ingest import IngestTask
from app.seed.dev_seed import USER_BOSS, USER_CONSULTANT, USER_PROJECT_MANAGER
from app.services import processing_timeout_recovery as recovery


def _headers(user_id):
    return {"X-Dev-User-Id": str(user_id)}


async def _timeout_task(db_session, storage, *, content: bytes | None, source="path_b_upload"):
    ref = (
        storage.save(content, original_name="sensitive-name.pdf")
        if content is not None
        else f"internal://{uuid.uuid4().hex}/missing.pdf"
    )
    task = IngestTask(
        source=source,
        source_file_ref=ref,
        source_file_name="sensitive-name.pdf",
        source_file_mime_type="application/pdf",
        source_file_size=999999,
        status="failed",
        error_type="processing_timeout",
        error_message="server path SECRET",
        created_by=USER_CONSULTANT,
    )
    db_session.add(task)
    await db_session.commit()
    return task


async def test_dry_run_is_aggregate_only_and_does_not_change_tasks(client, db_session, monkeypatch):
    available = [
        await _timeout_task(db_session, client._kap_storage, content=b"pdf" + bytes([index]))
        for index in range(3)
    ]
    empty = await _timeout_task(db_session, client._kap_storage, content=b"")
    missing = await _timeout_task(db_session, client._kap_storage, content=None)
    await _timeout_task(db_session, client._kap_storage, content=b"excluded", source="path_a_wecom")
    monkeypatch.setattr(
        recovery,
        "runtime_facts",
        lambda: _async_value(recovery._RuntimeFacts(True, True, 0, 7)),
    )

    response = await client.post(
        "/admin/ops/ingest/processing-timeout-recovery",
        headers=_headers(USER_BOSS),
        json={},
    )

    assert response.status_code == 200
    assert response.json() == {
        "dry_run": True,
        "scanned": 5,
        "candidates": 3,
        "source_unavailable": 2,
        "selected": 0,
        "claimed": 0,
        "enqueued": 0,
        "conflicts": 0,
        "stopped": False,
        "stop_reason": None,
        "preflight": {
            "redis_ready": True,
            "ocr_worker_ready": True,
            "queue_within_budget": True,
            "oom_kill_count": 7,
            "ready": True,
            "reason": None,
        },
        "next_batch_not_before": None,
    }
    assert "sensitive-name" not in response.text
    assert "internal://" not in response.text
    for task in [*available, empty, missing]:
        await db_session.refresh(task)
        assert task.status == "failed"
        assert task.error_type == "processing_timeout"
    event = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.action == "ingest.processing_timeout_recovery_dry_run"
            )
        )
    ).scalar_one()
    assert event.target_id is None
    assert event.extra["candidates"] == 3
    assert "sensitive-name" not in str(event.extra)


async def test_confirmed_batch_is_limited_claimed_and_stops_the_next_batch(
    client, db_session, monkeypatch
):
    available = [
        await _timeout_task(db_session, client._kap_storage, content=b"pdf" + bytes([index]))
        for index in range(4)
    ]
    empty = await _timeout_task(db_session, client._kap_storage, content=b"")
    enqueued: list[uuid.UUID] = []

    async def fake_facts():
        return recovery._RuntimeFacts(True, True, 0, 4)

    async def fake_enqueue(_session, task_id, **_kwargs):
        enqueued.append(task_id)
        return "processing"

    monkeypatch.setattr(recovery, "runtime_facts", fake_facts)
    monkeypatch.setattr(recovery, "enqueue_ingest_processing", fake_enqueue)

    executed = await client.post(
        "/admin/ops/ingest/processing-timeout-recovery",
        headers=_headers(USER_BOSS),
        json={"dry_run": False, "confirm": True, "limit": 3, "expected_oom_kill_count": 4},
    )

    assert executed.status_code == 200
    body = executed.json()
    assert (body["selected"], body["claimed"], body["enqueued"]) == (3, 3, 3)
    assert body["source_unavailable"] == 1
    assert len(enqueued) == 3
    for task in available:
        await db_session.refresh(task)
    assert sum(task.status == "processing" for task in available) == 3
    assert sum(task.status == "failed" for task in available) == 1
    assert all(task.error_type is None for task in available if task.status == "processing")
    await db_session.refresh(empty)
    assert empty.error_type == "source_file_unavailable"
    actions = set(
        (
            await db_session.execute(
                select(AuditEvent.action).where(
                    AuditEvent.action.in_(
                        {
                            "ingest.processing_timeout_recovery_confirmed",
                            "ingest.processing_timeout_recovery_enqueued",
                        }
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    assert actions == {
        "ingest.processing_timeout_recovery_confirmed",
        "ingest.processing_timeout_recovery_enqueued",
    }

    blocked = await client.post(
        "/admin/ops/ingest/processing-timeout-recovery",
        headers=_headers(USER_BOSS),
        json={"dry_run": False, "confirm": True, "limit": 3, "expected_oom_kill_count": 4},
    )
    assert blocked.status_code == 200
    assert blocked.json()["stopped"] is True
    assert blocked.json()["stop_reason"] == "batch_interval_not_elapsed"
    assert len(enqueued) == 3


async def test_recovery_requires_governance_or_admin(client):
    response = await client.post(
        "/admin/ops/ingest/processing-timeout-recovery",
        headers=_headers(USER_PROJECT_MANAGER),
        json={},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["denied_reason"] == "ingest_timeout_recovery_forbidden"


@pytest.mark.parametrize(
    ("facts", "expected_oom", "reason"),
    [
        (recovery._RuntimeFacts(False, False, 0, 2), 2, "redis_unavailable"),
        (recovery._RuntimeFacts(True, False, 0, 2), 2, "ocr_worker_unavailable"),
        (recovery._RuntimeFacts(True, True, 26, 2), 2, "queue_budget_exceeded"),
        (recovery._RuntimeFacts(True, True, 0, 3), 2, "oom_kill_count_changed"),
    ],
)
async def test_failed_preflight_stops_without_claim_or_enqueue(
    client, db_session, monkeypatch, facts, expected_oom, reason
):
    task = await _timeout_task(db_session, client._kap_storage, content=b"available")
    enqueue_calls = 0

    async def fake_facts():
        return facts

    async def fake_enqueue(*_args, **_kwargs):
        nonlocal enqueue_calls
        enqueue_calls += 1

    monkeypatch.setattr(recovery, "runtime_facts", fake_facts)
    monkeypatch.setattr(recovery, "enqueue_ingest_processing", fake_enqueue)

    response = await client.post(
        "/admin/ops/ingest/processing-timeout-recovery",
        headers=_headers(USER_BOSS),
        json={
            "dry_run": False,
            "confirm": True,
            "limit": 3,
            "expected_oom_kill_count": expected_oom,
        },
    )

    assert response.status_code == 200
    assert response.json()["stopped"] is True
    assert response.json()["stop_reason"] == reason
    assert enqueue_calls == 0
    await db_session.refresh(task)
    assert (task.status, task.error_type) == ("failed", "processing_timeout")
    event = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.action == "ingest.processing_timeout_recovery_preflight_rejected"
            )
        )
    ).scalar_one()
    assert event.extra["preflight"] == reason


async def test_single_task_dry_run_is_safe_and_does_not_expose_identifier(
    client, db_session, monkeypatch
):
    task = await _timeout_task(db_session, client._kap_storage, content=b"available")

    async def fake_facts():
        return recovery._RuntimeFacts(True, True, 0, 9)

    monkeypatch.setattr(recovery, "runtime_facts", fake_facts)
    response = await client.post(
        f"/admin/ops/ingest/processing-timeout-recovery/{task.id}",
        headers=_headers(USER_BOSS),
        json={},
    )

    assert response.status_code == 200
    assert response.json()["candidates"] == 1
    assert str(task.id) not in response.text
    assert "sensitive-name" not in response.text


async def test_enqueue_failure_is_audited_and_stops_remaining_candidates(
    client, db_session, monkeypatch
):
    tasks = [
        await _timeout_task(db_session, client._kap_storage, content=b"available" + bytes([index]))
        for index in range(2)
    ]

    async def fake_facts():
        return recovery._RuntimeFacts(True, True, 0, 5)

    async def failing_enqueue(*_args, **_kwargs):
        raise RuntimeError("sensitive transport detail")

    monkeypatch.setattr(recovery, "runtime_facts", fake_facts)
    monkeypatch.setattr(recovery, "enqueue_ingest_processing", failing_enqueue)
    response = await client.post(
        "/admin/ops/ingest/processing-timeout-recovery",
        headers=_headers(USER_BOSS),
        json={
            "dry_run": False,
            "confirm": True,
            "limit": 3,
            "expected_oom_kill_count": 5,
        },
    )

    assert response.status_code == 200
    assert response.json()["stopped"] is True
    assert response.json()["stop_reason"] == "queue_unavailable"
    assert (response.json()["claimed"], response.json()["enqueued"]) == (1, 0)
    assert "sensitive transport detail" not in response.text
    for task in tasks:
        await db_session.refresh(task)
    assert tasks[0].error_type == "processing_timeout"
    assert tasks[1].status == "failed"
    event = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.action == "ingest.processing_timeout_recovery_enqueue_failed"
            )
        )
    ).scalar_one()
    assert event.extra == {"reason": "queue_unavailable", "result": "not_enqueued"}


async def _async_value(value):
    return value

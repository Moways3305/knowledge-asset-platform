from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from starlette.datastructures import UploadFile

from app.api import ingest as ingest_api
from app.models.audit import AuditEvent
from app.models.ingest import IngestTask, UploadSessionItem, UploadTransportBatch
from app.models.review import ReviewTask
from app.schemas.enums import AuditAction, IngestSource, IngestStatus, ReviewTaskStatus, ReviewType
from app.seed.dev_seed import (
    KA_PROJECT_ALPHA_REVIEWABLE,
    PROJECT_ALPHA,
    USER_ADMIN_ONLY,
    USER_CONSULTANT,
    USER_PROJECT_MANAGER,
)
from app.services import upload_session_recovery
from app.services.desensitization import NullDesensitizer
from app.services.jobs import ingest_processing
from app.services.jobs.ingest_cancellation import cleanup_cancelled_tasks
from app.services.llm_client import NullLLMClient
from app.services.upload_sessions import BATCH_SIZE, stable_batch_sizes


def _headers(user_id):
    return {"X-Dev-User-Id": str(user_id)}


def test_stable_batch_boundaries_are_unbounded_and_keep_partial_tail():
    assert BATCH_SIZE == 200
    assert stable_batch_sizes(0) == []
    assert stable_batch_sizes(201) == [200, 1]
    assert stable_batch_sizes(400) == [200, 200]
    assert stable_batch_sizes(401) == [200, 200, 1]
    assert stable_batch_sizes(700) == [200, 200, 200, 100]


async def test_transport_manifest_accepts_the_protocol_maximum_of_1000_items(client):
    session_id = uuid.uuid4()
    manifest = [
        {
            "client_file_key": f"file-{index}",
            "file_name": f"file-{index}.txt",
            "file_size": 1,
            "transport_batch_index": index // 10,
        }
        for index in range(1000)
    ]
    response = await client.post(
        "/api/v1/ingest/upload-sessions/init",
        headers=_headers(USER_CONSULTANT),
        json={
            "session_id": str(session_id),
            "total_transport_batches": 100,
            "manifest": manifest,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_files"] == 1000
    assert body["total_batches"] == 100
    assert len(body["items"]) == 1000


async def test_transport_session_is_durable_ordered_and_batch_idempotent(client, db_session):
    session_id = uuid.uuid4()
    initialized = await client.post(
        "/api/v1/ingest/upload-sessions/init",
        headers=_headers(USER_CONSULTANT),
        json={
            "session_id": str(session_id),
            "total_transport_batches": 2,
            "manifest": [
                {
                    "client_file_key": "a",
                    "file_name": "a.txt",
                    "file_size": 1,
                    "transport_batch_index": 0,
                },
                {
                    "client_file_key": "b",
                    "file_name": "b.txt",
                    "file_size": 1,
                    "transport_batch_index": 1,
                },
            ],
        },
    )
    assert initialized.status_code == 200
    body = initialized.json()
    assert body["uploaded_files"] == 0
    assert body["upload_completed"] is False
    item_ids = [item["id"] for item in body["items"]]

    out_of_order = await client.post(
        f"/api/v1/ingest/upload-sessions/{session_id}/batches",
        headers=_headers(USER_CONSULTANT),
        data={"batch_id": "batch-1", "batch_index": "1", "item_ids": f'["{item_ids[1]}"]'},
        files={"files": ("b.txt", b"b", "text/plain")},
    )
    assert out_of_order.status_code == 409
    assert not any(path.is_file() for path in client._kap_storage.root.rglob("*"))

    request = {
        "headers": _headers(USER_CONSULTANT),
        "data": {"batch_id": "batch-0", "batch_index": "0", "item_ids": f'["{item_ids[0]}"]'},
        "files": {"files": ("a.txt", b"a", "text/plain")},
    }
    first = await client.post(f"/api/v1/ingest/upload-sessions/{session_id}/batches", **request)
    repeated = await client.post(f"/api/v1/ingest/upload-sessions/{session_id}/batches", **request)
    assert first.status_code == repeated.status_code == 200
    assert repeated.json()["uploaded_files"] == 1
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(UploadTransportBatch)
            .where(UploadTransportBatch.session_id == session_id)
        )
        == 1
    )


async def test_failed_transport_context_survives_and_row_bytes_can_be_reselected(client):
    session_id = uuid.uuid4()
    initialized = await client.post(
        "/api/v1/ingest/upload-sessions/init",
        headers=_headers(USER_CONSULTANT),
        json={
            "session_id": str(session_id),
            "total_transport_batches": 1,
            "manifest": [
                {
                    "client_file_key": "a",
                    "file_name": "recover.txt",
                    "file_size": 7,
                    "transport_batch_index": 0,
                }
            ],
        },
    )
    item_id = initialized.json()["items"][0]["id"]
    failed = await client.post(
        f"/api/v1/ingest/upload-sessions/{session_id}/transport-failure",
        headers=_headers(USER_CONSULTANT),
        json={
            "item_ids": [item_id],
            "error_code": "proxy_rejected",
            "batch_id": "batch-0",
            "batch_index": 0,
        },
    )
    assert failed.status_code == 200
    assert failed.json()["items"][0]["error_code"] == "proxy_rejected"
    assert failed.json()["items"][0]["bytes_available"] is False

    replaced = await client.post(
        f"/api/v1/ingest/upload-sessions/{session_id}/items/{item_id}/bytes",
        headers=_headers(USER_CONSULTANT),
        files={"file": ("recover.txt", b"recover", "text/plain")},
    )
    assert replaced.status_code == 200
    assert replaced.json()["uploaded_files"] == 1
    assert replaced.json()["items"][0]["bytes_available"] is True

    completed = await client.post(
        f"/api/v1/ingest/upload-sessions/{session_id}/complete",
        headers=_headers(USER_CONSULTANT),
    )
    assert completed.status_code == 200
    assert completed.json()["upload_completed"] is True


async def test_cancel_upload_session_removes_unfinished_bytes_and_hides_items(client, db_session):
    session_id = uuid.uuid4()
    initialized = await client.post(
        "/api/v1/ingest/upload-sessions/init",
        headers=_headers(USER_CONSULTANT),
        json={
            "session_id": str(session_id),
            "total_transport_batches": 1,
            "manifest": [
                {
                    "client_file_key": "cancel-me",
                    "file_name": "cancel-me.txt",
                    "file_size": 7,
                    "transport_batch_index": 0,
                }
            ],
        },
    )
    item_id = initialized.json()["items"][0]["id"]
    uploaded = await client.post(
        f"/api/v1/ingest/upload-sessions/{session_id}/batches",
        headers=_headers(USER_CONSULTANT),
        data={"batch_id": "batch-0", "batch_index": "0", "item_ids": f'["{item_id}"]'},
        files={"files": ("cancel-me.txt", b"cancel!", "text/plain")},
    )
    assert uploaded.status_code == 200
    item = await db_session.get(UploadSessionItem, uuid.UUID(item_id))
    assert item is not None and item.ingest_task_id is not None
    task_id = item.ingest_task_id

    cancelled = await client.post(
        f"/api/v1/ingest/upload-sessions/{session_id}/cancel",
        headers=_headers(USER_CONSULTANT),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["upload_completed"] is True
    assert cancelled.json()["items"] == []
    task = await db_session.get(IngestTask, task_id)
    assert task is not None
    assert task.status == IngestStatus.cancelled.value
    assert task.cancel_requested is True
    assert {
        AuditAction.ingest_cancellation_requested.value,
        AuditAction.upload_session_cancelled.value,
    }.issubset(
        set(
            (
                await db_session.execute(
                    select(AuditEvent.action).where(AuditEvent.target_id.in_([task_id, session_id]))
                )
            ).scalars()
        )
    )
    assert any(path.is_file() for path in client._kap_storage.root.rglob("*"))

    assert (
        await cleanup_cancelled_tasks(
            db_session,
            client._kap_storage,
            task_ids=(task_id,),
        )
        == 1
    )
    assert await db_session.get(IngestTask, task_id) is None
    assert (
        await db_session.scalar(
            select(AuditEvent.action).where(
                AuditEvent.target_id == task_id,
                AuditEvent.action == AuditAction.ingest_cancellation_cleaned.value,
            )
        )
        == AuditAction.ingest_cancellation_cleaned.value
    )
    assert not any(path.is_file() for path in client._kap_storage.root.rglob("*"))


async def test_cancel_preserves_confirmed_item_and_only_cancels_remaining_work(client, db_session):
    session_id = uuid.uuid4()
    initialized = await client.post(
        "/api/v1/ingest/upload-sessions/init",
        headers=_headers(USER_CONSULTANT),
        json={
            "session_id": str(session_id),
            "total_transport_batches": 1,
            "manifest": [
                {
                    "client_file_key": "confirmed",
                    "file_name": "confirmed.txt",
                    "file_size": 9,
                    "transport_batch_index": 0,
                },
                {
                    "client_file_key": "unfinished",
                    "file_name": "unfinished.txt",
                    "file_size": 10,
                    "transport_batch_index": 0,
                },
            ],
        },
    )
    item_ids = [item["id"] for item in initialized.json()["items"]]
    uploaded = await client.post(
        f"/api/v1/ingest/upload-sessions/{session_id}/batches",
        headers=_headers(USER_CONSULTANT),
        data={"batch_id": "batch-0", "batch_index": "0", "item_ids": json.dumps(item_ids)},
        files=[
            ("files", ("confirmed.txt", b"confirmed", "text/plain")),
            ("files", ("unfinished.txt", b"unfinished", "text/plain")),
        ],
    )
    assert uploaded.status_code == 200
    confirmed_item = await db_session.get(UploadSessionItem, uuid.UUID(item_ids[0]))
    unfinished_item = await db_session.get(UploadSessionItem, uuid.UUID(item_ids[1]))
    assert confirmed_item is not None and confirmed_item.ingest_task_id is not None
    assert unfinished_item is not None and unfinished_item.ingest_task_id is not None
    confirmed_task = await db_session.get(IngestTask, confirmed_item.ingest_task_id)
    unfinished_task = await db_session.get(IngestTask, unfinished_item.ingest_task_id)
    assert confirmed_task is not None and unfinished_task is not None

    # This is the serialized outcome when confirmation wins the task row lock,
    # while the session item still contains its earlier projection.
    confirmed_task.status = IngestStatus.completed.value
    confirmed_task.result_asset_id = KA_PROJECT_ALPHA_REVIEWABLE
    confirmed_item.status = "awaiting_confirmation"
    await db_session.commit()
    confirmed_task_id = confirmed_task.id
    unfinished_task_id = unfinished_task.id

    response = await client.post(
        f"/api/v1/ingest/upload-sessions/{session_id}/cancel",
        headers=_headers(USER_CONSULTANT),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["upload_completed"] is True
    assert [item["id"] for item in response.json()["items"]] == [str(confirmed_item.id)]
    assert response.json()["items"][0]["status"] == "completed"
    db_session.expire_all()
    confirmed_task = await db_session.get(IngestTask, confirmed_task_id)
    unfinished_task = await db_session.get(IngestTask, unfinished_task_id)
    assert confirmed_task is not None
    assert confirmed_task.result_asset_id == KA_PROJECT_ALPHA_REVIEWABLE
    assert confirmed_task.cancel_requested is False
    assert unfinished_task is not None and unfinished_task.cancel_requested is True

    listing = await client.get("/api/v1/ingest/upload-sessions", headers=_headers(USER_CONSULTANT))
    assert any(item["id"] == str(session_id) for item in listing.json()["items"])


async def test_cancelled_transport_session_rejects_late_batch_and_cannot_be_revived(
    client, db_session
):
    session_id = uuid.uuid4()
    initialized = await client.post(
        "/api/v1/ingest/upload-sessions/init",
        headers=_headers(USER_CONSULTANT),
        json={
            "session_id": str(session_id),
            "total_transport_batches": 1,
            "manifest": [
                {
                    "client_file_key": "late-item",
                    "file_name": "late.txt",
                    "file_size": 4,
                    "transport_batch_index": 0,
                }
            ],
        },
    )
    item_id = initialized.json()["items"][0]["id"]

    cancelled = await client.post(
        f"/api/v1/ingest/upload-sessions/{session_id}/cancel",
        headers=_headers(USER_CONSULTANT),
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["upload_completed"] is True

    queried = await client.get(
        f"/api/v1/ingest/upload-sessions/{session_id}",
        headers=_headers(USER_CONSULTANT),
    )
    assert queried.status_code == 200
    assert queried.json()["status"] == "cancelled"
    assert queried.json()["upload_completed"] is True
    listing = await client.get(
        "/api/v1/ingest/upload-sessions",
        headers=_headers(USER_CONSULTANT),
    )
    assert listing.status_code == 200
    assert all(entry["id"] != str(session_id) for entry in listing.json()["items"])

    late = await client.post(
        f"/api/v1/ingest/upload-sessions/{session_id}/batches",
        headers=_headers(USER_CONSULTANT),
        data={"batch_id": "batch-0", "batch_index": "0", "item_ids": f'["{item_id}"]'},
        files={"files": ("late.txt", b"late", "text/plain")},
    )
    assert late.status_code == 409
    assert late.json()["detail"]["denied_reason"] == "upload_session_cancelled"
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(IngestTask)
            .where(IngestTask.source_file_name == "late.txt")
        )
        == 0
    )
    assert not any(path.is_file() for path in client._kap_storage.root.rglob("*"))

    reselected = await client.post(
        f"/api/v1/ingest/upload-sessions/{session_id}/items/{item_id}/bytes",
        headers=_headers(USER_CONSULTANT),
        files={"file": ("late.txt", b"late", "text/plain")},
    )
    assert reselected.status_code == 409
    assert reselected.json()["detail"]["denied_reason"] == "upload_session_cancelled"
    assert not any(path.is_file() for path in client._kap_storage.root.rglob("*"))

    retried = await client.post(
        f"/api/v1/ingest/upload-sessions/{session_id}/items/{item_id}/retry",
        headers=_headers(USER_CONSULTANT),
    )
    assert retried.status_code == 409
    assert retried.json()["detail"]["denied_reason"] == "upload_session_cancelled"

    completed = await client.post(
        f"/api/v1/ingest/upload-sessions/{session_id}/complete",
        headers=_headers(USER_CONSULTANT),
    )
    assert completed.status_code == 409
    assert completed.json()["detail"]["denied_reason"] == "upload_session_cancelled"


async def test_cancel_marks_running_worker_task_without_deleting_its_row_or_source(
    client, db_session
):
    session_id = uuid.uuid4()
    initialized = await client.post(
        "/api/v1/ingest/upload-sessions/init",
        headers=_headers(USER_CONSULTANT),
        json={
            "session_id": str(session_id),
            "total_transport_batches": 1,
            "manifest": [
                {
                    "client_file_key": "running-item",
                    "file_name": "running.txt",
                    "file_size": 7,
                    "transport_batch_index": 0,
                }
            ],
        },
    )
    item_id = initialized.json()["items"][0]["id"]
    uploaded = await client.post(
        f"/api/v1/ingest/upload-sessions/{session_id}/batches",
        headers=_headers(USER_CONSULTANT),
        data={"batch_id": "batch-0", "batch_index": "0", "item_ids": f'["{item_id}"]'},
        files={"files": ("running.txt", b"running", "text/plain")},
    )
    assert uploaded.status_code == 200
    item = await db_session.get(UploadSessionItem, uuid.UUID(item_id))
    assert item is not None and item.ingest_task_id is not None
    task = await db_session.get(IngestTask, item.ingest_task_id)
    assert task is not None
    task.status = IngestStatus.processing.value
    task.processing_stage = "text_extraction"
    task.processing_worker_id = "worker@test"
    task.processing_job_id = "job-1"
    item.status = "processing"
    await db_session.commit()

    cancelled = await client.post(
        f"/api/v1/ingest/upload-sessions/{session_id}/cancel",
        headers=_headers(USER_CONSULTANT),
    )

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    await db_session.refresh(task)
    assert task.status == IngestStatus.processing.value
    assert task.cancel_requested is True
    assert task.processing_job_id == "job-1"
    assert client._kap_storage.exists(task.source_file_ref)


async def test_cancel_waiting_review_closes_review_and_retains_only_a_cleaned_task_record(
    client, db_session
):
    session_id = uuid.uuid4()
    initialized = await client.post(
        "/api/v1/ingest/upload-sessions/init",
        headers=_headers(USER_CONSULTANT),
        json={
            "session_id": str(session_id),
            "total_transport_batches": 1,
            "manifest": [
                {
                    "client_file_key": "review-item",
                    "file_name": "review.txt",
                    "file_size": 6,
                    "transport_batch_index": 0,
                }
            ],
        },
    )
    item_id = initialized.json()["items"][0]["id"]
    uploaded = await client.post(
        f"/api/v1/ingest/upload-sessions/{session_id}/batches",
        headers=_headers(USER_CONSULTANT),
        data={"batch_id": "batch-0", "batch_index": "0", "item_ids": f'["{item_id}"]'},
        files={"files": ("review.txt", b"review", "text/plain")},
    )
    assert uploaded.status_code == 200
    item = await db_session.get(UploadSessionItem, uuid.UUID(item_id))
    assert item is not None and item.ingest_task_id is not None
    task = await db_session.get(IngestTask, item.ingest_task_id)
    assert task is not None
    task.status = IngestStatus.waiting_review.value
    review = ReviewTask(
        review_type=ReviewType.project_ingest_approval.value,
        trigger_source="path_b_upload",
        source_ingest_task_id=task.id,
        target_project_id=PROJECT_ALPHA,
        target_scope="project",
        status=ReviewTaskStatus.pending_reviewer.value,
        reviewer_user_id=USER_PROJECT_MANAGER,
        submitted_by=USER_CONSULTANT,
        confirmation_snapshot={},
    )
    db_session.add(review)
    await db_session.commit()
    task_id = task.id
    review_id = review.id

    cancelled = await client.post(
        f"/api/v1/ingest/upload-sessions/{session_id}/cancel",
        headers=_headers(USER_CONSULTANT),
    )

    assert cancelled.status_code == 200
    db_session.expire_all()
    task = await db_session.get(IngestTask, task_id)
    review = await db_session.get(ReviewTask, review_id)
    assert task is not None and task.status == IngestStatus.cancelled.value
    assert review is not None and review.status == ReviewTaskStatus.cancelled.value
    assert review.reviewed_at is not None
    assert (
        await db_session.scalar(
            select(AuditEvent.action).where(
                AuditEvent.target_id == review_id,
                AuditEvent.action == AuditAction.review_cancelled.value,
            )
        )
        == AuditAction.review_cancelled.value
    )
    source_ref = task.source_file_ref

    assert (
        await cleanup_cancelled_tasks(
            db_session,
            client._kap_storage,
            task_ids=(task_id,),
        )
        == 1
    )
    db_session.expire_all()
    retained = await db_session.get(IngestTask, task_id)
    assert retained is not None and retained.cancellation_cleaned_at is not None
    assert await db_session.get(ReviewTask, review_id) is not None
    assert not client._kap_storage.exists(source_ref)


async def test_cancel_during_content_generation_prevents_final_worker_persistence(
    client, db_session, sessionmaker_fixture, monkeypatch
):
    session_id = uuid.uuid4()
    initialized = await client.post(
        "/api/v1/ingest/upload-sessions/init",
        headers=_headers(USER_CONSULTANT),
        json={
            "session_id": str(session_id),
            "total_transport_batches": 1,
            "manifest": [
                {
                    "client_file_key": "race-item",
                    "file_name": "race.txt",
                    "file_size": 12,
                    "transport_batch_index": 0,
                }
            ],
        },
    )
    item_id = initialized.json()["items"][0]["id"]
    uploaded = await client.post(
        f"/api/v1/ingest/upload-sessions/{session_id}/batches",
        headers=_headers(USER_CONSULTANT),
        data={"batch_id": "batch-0", "batch_index": "0", "item_ids": f'["{item_id}"]'},
        files={"files": ("race.txt", b"race content", "text/plain")},
    )
    assert uploaded.status_code == 200
    item = await db_session.get(UploadSessionItem, uuid.UUID(item_id))
    assert item is not None and item.ingest_task_id is not None
    task_id = item.ingest_task_id
    task = await db_session.get(IngestTask, task_id)
    assert task is not None
    task.status = IngestStatus.processing.value
    task.processing_stage = "upload_saved"
    item.status = "processing"
    await db_session.commit()

    generation_started = asyncio.Event()
    resume_generation = asyncio.Event()

    async def delayed_cached_draft(*_args, **_kwargs):
        generation_started.set()
        await resume_generation.wait()
        return {
            "suggested_title": "must-not-persist",
            "naming_parsed_fields": {"generation_status": "generated"},
        }

    monkeypatch.setattr(ingest_processing, "_reusable_ai_draft", delayed_cached_draft)

    async def run_worker():
        async with sessionmaker_fixture() as worker_session:
            return await ingest_processing.process_upload_task(
                worker_session,
                task_id,
                storage=client._kap_storage,
                llm=NullLLMClient(),
                desensitizer=NullDesensitizer(),
                trace_id="cancel-race",
                worker_id="worker@test",
                job_id="race-job",
            )

    worker = asyncio.create_task(run_worker())
    await asyncio.wait_for(generation_started.wait(), timeout=5)
    cancelled = await client.post(
        f"/api/v1/ingest/upload-sessions/{session_id}/cancel",
        headers=_headers(USER_CONSULTANT),
    )
    assert cancelled.status_code == 200
    resume_generation.set()

    assert await asyncio.wait_for(worker, timeout=5) == IngestStatus.cancelled.value
    db_session.expire_all()
    task = await db_session.get(IngestTask, task_id)
    assert task is not None
    assert task.status == IngestStatus.cancelled.value
    assert task.cancel_requested is True
    assert task.processing_job_id is None
    await db_session.refresh(task, attribute_names=["ai_result", "canonical_markdown"])
    assert task.ai_result is not None
    derivative_ref = task.canonical_markdown.storage_ref if task.canonical_markdown else None
    assert derivative_ref and client._kap_storage.exists(derivative_ref)

    assert (
        await cleanup_cancelled_tasks(
            db_session,
            client._kap_storage,
            task_ids=(task_id,),
        )
        == 1
    )
    assert await db_session.get(IngestTask, task_id) is None
    assert not client._kap_storage.exists(derivative_ref)


async def test_upload_session_persists_all_items_and_separates_same_name_from_hash(client):
    response = await client.post(
        "/api/v1/ingest/upload-sessions",
        headers=_headers(USER_CONSULTANT),
        files=[
            ("files", ("same-name.txt", b"first body", "text/plain")),
            ("files", ("same-name.txt", b"different body", "text/plain")),
            ("files", ("unsafe.exe", b"not accepted", "application/octet-stream")),
        ],
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_files"] == 3
    assert body["total_batches"] == 1
    assert [item["ordinal"] for item in body["items"]] == [0, 1, 2]
    assert body["items"][0]["same_name_warning"] is False
    assert body["items"][1]["same_name_warning"] is True
    assert body["items"][2]["status"] == "failed"
    assert body["items"][2]["error_code"] == "unsupported_file_type"
    assert "source_file_ref" not in response.text
    assert "storage_ref" not in response.text
    assert "internal://" not in response.text

    recovered = await client.get(
        f"/api/v1/ingest/upload-sessions/{body['id']}",
        headers=_headers(USER_CONSULTANT),
    )
    assert recovered.status_code == 200
    assert [item["file_name"] for item in recovered.json()["items"]] == [
        "same-name.txt",
        "same-name.txt",
        "unsafe.exe",
    ]


async def test_same_name_warning_ignores_completed_history_but_keeps_pending_tasks(
    client, db_session
):
    db_session.add_all(
        [
            IngestTask(
                source=IngestSource.path_b_upload.value,
                source_file_ref="internal://test/completed",
                source_file_name="completed-history.txt",
                status=IngestStatus.completed.value,
                created_by=USER_CONSULTANT,
            ),
            IngestTask(
                source=IngestSource.path_b_upload.value,
                source_file_ref="internal://test/pending",
                source_file_name="pending-item.txt",
                status=IngestStatus.pending_confirmation.value,
                created_by=USER_CONSULTANT,
            ),
        ]
    )
    await db_session.commit()

    response = await client.post(
        "/api/v1/ingest/upload-sessions",
        headers=_headers(USER_CONSULTANT),
        files=[
            ("files", ("completed-history.txt", b"new completed-name body", "text/plain")),
            ("files", ("pending-item.txt", b"new pending-name body", "text/plain")),
        ],
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert items[0]["same_name_warning"] is False
    assert items[1]["same_name_warning"] is True


async def test_upload_sessions_are_caller_scoped_and_do_not_enumerate_other_users(client):
    created = await client.post(
        "/api/v1/ingest/upload-sessions",
        headers=_headers(USER_CONSULTANT),
        files={"files": ("private-name.txt", b"private", "text/plain")},
    )
    session_id = created.json()["id"]

    direct = await client.get(
        f"/api/v1/ingest/upload-sessions/{session_id}",
        headers=_headers(USER_PROJECT_MANAGER),
    )
    assert direct.status_code == 404
    assert direct.json()["detail"]["denied_reason"] == "upload_session_not_found"

    listing = await client.get(
        "/api/v1/ingest/upload-sessions",
        headers=_headers(USER_PROJECT_MANAGER),
    )
    assert listing.status_code == 200
    assert all(item["id"] != session_id for item in listing.json()["items"])
    assert "private-name.txt" not in listing.text


async def test_client_session_id_makes_lost_response_retry_idempotent(client):
    session_id = uuid.uuid4()
    request = {
        "headers": _headers(USER_CONSULTANT),
        "data": {"session_id": str(session_id)},
        "files": {"files": ("idempotent.txt", b"once", "text/plain")},
    }
    first = await client.post("/api/v1/ingest/upload-sessions", **request)
    second = await client.post("/api/v1/ingest/upload-sessions", **request)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == str(session_id)
    assert second.json()["id"] == str(session_id)
    assert second.json()["total_files"] == 1


async def test_next_batch_waits_then_advances_when_the_current_batch_releases_capacity(
    client, db_session, monkeypatch
):
    async def queued_without_worker(*args, **kwargs):
        return "processing"

    monkeypatch.setattr(upload_session_recovery, "enqueue_ingest_processing", queued_without_worker)
    files = [("files", (f"ordered-{index:03}.txt", b"x", "text/plain")) for index in range(401)]
    created = await client.post(
        "/api/v1/ingest/upload-sessions",
        headers=_headers(USER_CONSULTANT),
        files=files,
    )
    assert created.status_code == 200
    body = created.json()
    assert body["total_files"] == 401
    assert body["total_batches"] == 3
    assert [item["batch_number"] for item in body["items"]].count(1) == 200
    assert [item["batch_number"] for item in body["items"]].count(2) == 200
    assert [item["batch_number"] for item in body["items"]].count(3) == 1
    assert all(item["status"] == "processing" for item in body["items"][:5])
    assert all(item["status"] == "waiting" for item in body["items"][5:])

    first_batch_task_ids = list(
        (
            await db_session.execute(
                select(UploadSessionItem.ingest_task_id)
                .where(
                    UploadSessionItem.session_id == uuid.UUID(body["id"]),
                    UploadSessionItem.batch_index == 0,
                )
                .order_by(UploadSessionItem.ordinal)
            )
        ).scalars()
    )
    tasks = list(
        (
            await db_session.execute(
                select(IngestTask).where(IngestTask.id.in_(first_batch_task_ids))
            )
        ).scalars()
    )
    next(
        task for task in tasks if task.id == first_batch_task_ids[0]
    ).processing_stage = "canonical_markdown_generation"
    await db_session.commit()
    staged = await client.get(
        f"/api/v1/ingest/upload-sessions/{body['id']}",
        headers=_headers(USER_CONSULTANT),
    )
    assert staged.status_code == 200
    assert staged.json()["items"][0]["processing_stage"] == "canonical_markdown_generation"
    assert staged.json()["items"][200]["processing_stage"] is None

    for task in tasks:
        if task.id != first_batch_task_ids[0]:
            continue
        task.status = IngestStatus.pending_confirmation.value
        task.processing_stage = "awaiting_confirmation"
    await db_session.commit()

    advanced = await client.get(
        f"/api/v1/ingest/upload-sessions/{body['id']}",
        headers=_headers(USER_CONSULTANT),
    )
    assert advanced.status_code == 200
    next_body = advanced.json()
    assert next_body["items"][0]["status"] == "awaiting_confirmation"
    assert all(item["status"] == "processing" for item in next_body["items"][1:6])
    assert all(item["status"] == "waiting" for item in next_body["items"][6:])
    # Polling again cannot dispatch extra files or duplicate the five active jobs.
    repeated = await client.get(
        f"/api/v1/ingest/upload-sessions/{body['id']}", headers=_headers(USER_CONSULTANT)
    )
    assert sum(item["status"] == "processing" for item in repeated.json()["items"]) == 5


async def test_macos_metadata_is_rejected_before_task_creation_without_false_positives(
    client, db_session
):
    before = (await db_session.execute(select(func.count()).select_from(IngestTask))).scalar_one()
    response = await client.post(
        "/api/v1/ingest/upload-sessions",
        headers=_headers(USER_CONSULTANT),
        files=[
            ("files", ("._foo.md", b"apple-double", "text/markdown")),
            ("files", (".DS_Store", b"finder", "application/octet-stream")),
            ("files", (".notes.md", b"real hidden note", "text/markdown")),
            ("files", ("中文 资料.md", b"real chinese note", "text/markdown")),
        ],
        data={
            "client_rejections": (
                '[{"file_name":"__MACOSX/._archive.md","file_size":12,'
                '"error_code":"macos_metadata"}]'
            )
        },
    )
    assert response.status_code == 200
    body = response.json()
    failures = {item["file_name"]: item for item in body["items"] if item["status"] == "failed"}
    assert failures["._foo.md"]["error_code"] == "macos_metadata"
    assert failures[".DS_Store"]["error_code"] == "macos_metadata"
    assert failures["._archive.md"]["error_code"] == "macos_metadata"
    assert "macOS 元数据文件" in failures["._foo.md"]["error_message"]
    assert all(
        "/" not in item["file_name"] and "\\" not in item["file_name"] for item in body["items"]
    )
    after = (await db_session.execute(select(func.count()).select_from(IngestTask))).scalar_one()
    assert after - before == 2


async def test_legacy_single_upload_rejects_macos_metadata_before_task_creation(client, db_session):
    before = (await db_session.execute(select(func.count()).select_from(IngestTask))).scalar_one()
    response = await client.post(
        "/api/v1/ingest/upload",
        headers=_headers(USER_CONSULTANT),
        files={"file": ("._legacy.md", b"metadata", "text/markdown")},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["denied_reason"] == "macos_metadata"
    assert "macOS 元数据文件" in response.json()["detail"]["message"]
    after = (await db_session.execute(select(func.count()).select_from(IngestTask))).scalar_one()
    assert after == before


async def test_unreadable_upload_is_a_terminal_item_without_a_task(client, db_session, monkeypatch):
    async def unreadable(self, size=-1):
        raise OSError("private provider detail")

    monkeypatch.setattr(UploadFile, "read", unreadable)
    before = (await db_session.execute(select(func.count()).select_from(IngestTask))).scalar_one()
    response = await client.post(
        "/api/v1/ingest/upload-sessions",
        headers=_headers(USER_CONSULTANT),
        files={"files": ("cloud.docx", b"placeholder", "application/octet-stream")},
    )
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["status"] == "failed"
    assert item["error_code"] == "file_unreadable"
    assert item["error_message"] == "文件内容当前不可读取；请先在本机完成下载后重新选择"
    assert "private provider detail" not in response.text
    after = (await db_session.execute(select(func.count()).select_from(IngestTask))).scalar_one()
    assert after == before


async def test_upload_read_timeout_is_terminal_without_a_task(client, db_session, monkeypatch):
    async def slow_read(self, size=-1):
        await asyncio.sleep(0.05)
        return b"late"

    monkeypatch.setattr(UploadFile, "read", slow_read)
    monkeypatch.setattr(ingest_api, "_UPLOAD_READ_TIMEOUT_SECONDS", 0.001)
    before = (await db_session.execute(select(func.count()).select_from(IngestTask))).scalar_one()
    response = await client.post(
        "/api/v1/ingest/upload-sessions",
        headers=_headers(USER_CONSULTANT),
        files={"files": ("cloud.docx", b"placeholder", "application/octet-stream")},
    )
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["status"] == "failed"
    assert item["error_code"] == "file_read_timeout"
    after = (await db_session.execute(select(func.count()).select_from(IngestTask))).scalar_one()
    assert after == before


async def test_stale_processing_requires_total_age_and_missing_recent_activity(
    client, db_session, monkeypatch
):
    async def queued_without_worker(*args, **kwargs):
        return "processing"

    monkeypatch.setattr(upload_session_recovery, "enqueue_ingest_processing", queued_without_worker)
    created = await client.post(
        "/api/v1/ingest/upload-sessions",
        headers=_headers(USER_CONSULTANT),
        files=[
            ("files", ("stale.txt", b"stale", "text/plain")),
            ("files", ("active.txt", b"active", "text/plain")),
        ],
    )
    assert created.status_code == 200
    item_task_ids = list(
        (
            await db_session.execute(
                select(UploadSessionItem.ingest_task_id)
                .where(UploadSessionItem.session_id == uuid.UUID(created.json()["id"]))
                .order_by(UploadSessionItem.ordinal)
            )
        ).scalars()
    )
    stale, active = list(
        (
            await db_session.execute(
                select(IngestTask)
                .where(IngestTask.id.in_(item_task_ids))
                .order_by(IngestTask.source_file_name.desc())
            )
        ).scalars()
    )
    now = datetime.now(timezone.utc)
    stale.created_at = now - timedelta(hours=3)
    stale.updated_at = now - timedelta(minutes=30)
    active.created_at = now - timedelta(hours=3)
    active.updated_at = now - timedelta(minutes=5)
    await db_session.commit()

    recovered = await client.get(
        f"/api/v1/ingest/upload-sessions/{created.json()['id']}",
        headers=_headers(USER_CONSULTANT),
    )
    assert recovered.status_code == 200
    statuses = {item["file_name"]: item for item in recovered.json()["items"]}
    assert statuses[stale.source_file_name]["status"] == "failed"
    assert statuses[stale.source_file_name]["error_code"] == "processing_timeout"
    assert statuses[active.source_file_name]["status"] == "processing"

    repeated = await client.get(
        f"/api/v1/ingest/upload-sessions/{created.json()['id']}",
        headers=_headers(USER_CONSULTANT),
    )
    assert repeated.status_code == 200
    assert repeated.json()["failed_files"] == 1


async def test_admin_stale_scan_never_overwrites_a_cancellation_request(client, db_session):
    stale = datetime.now(timezone.utc) - timedelta(hours=3)
    task = IngestTask(
        source=IngestSource.path_b_upload.value,
        source_file_ref="internal://cancel-pending/stale.txt",
        source_file_name="cancel-pending-stale.txt",
        source_file_size=10,
        status=IngestStatus.processing.value,
        processing_stage="text_extraction",
        processing_started_at=stale,
        processing_heartbeat_at=stale,
        processing_worker_id="lost-worker",
        processing_job_id="lost-job",
        cancel_requested=True,
        created_by=USER_CONSULTANT,
    )
    db_session.add(task)
    await db_session.commit()

    response = await client.get("/api/v1/admin/ingest", headers=_headers(USER_ADMIN_ONLY))

    assert response.status_code == 200
    await db_session.refresh(task)
    assert task.status == IngestStatus.processing.value
    assert task.cancel_requested is True
    assert task.error_type is None


async def test_bulk_failed_cleanup_is_caller_scoped_and_immediately_hides_items(client):
    created = await client.post(
        "/api/v1/ingest/upload-sessions",
        headers=_headers(USER_CONSULTANT),
        files={"files": ("unsafe.exe", b"blocked", "application/octet-stream")},
    )
    assert created.status_code == 200
    session_id = created.json()["id"]

    denied = await client.delete(
        f"/api/v1/ingest/upload-sessions/{session_id}/failed-items",
        headers=_headers(USER_PROJECT_MANAGER),
    )
    assert denied.status_code == 404

    cleaned = await client.delete(
        f"/api/v1/ingest/upload-sessions/{session_id}/failed-items",
        headers=_headers(USER_CONSULTANT),
    )
    assert cleaned.status_code == 200
    assert cleaned.json()["items"] == []
    repeated = await client.delete(
        f"/api/v1/ingest/upload-sessions/{session_id}/failed-items",
        headers=_headers(USER_CONSULTANT),
    )
    assert repeated.status_code == 200
    assert repeated.json()["items"] == []


async def test_item_retry_atomically_claims_the_failed_row_before_enqueue(
    client, db_session, monkeypatch
):
    created = await client.post(
        "/api/v1/ingest/upload-sessions",
        headers=_headers(USER_CONSULTANT),
        files={"files": ("retry.txt", b"retry body", "text/plain")},
    )
    assert created.status_code == 200
    session_id = created.json()["id"]
    item_id = created.json()["items"][0]["id"]
    item = await db_session.get(UploadSessionItem, uuid.UUID(item_id))
    task = await db_session.get(IngestTask, item.ingest_task_id)
    item.status = "failed"
    task.status = IngestStatus.failed.value
    task.processing_stage = "content_generation_failed"
    task.error_type = "timeout"
    await db_session.commit()

    retry_url = f"/api/v1/ingest/upload-sessions/{session_id}/items/{item_id}/retry"
    enqueue_calls = 0
    competing_status = None

    async def fake_enqueue(*_args, **_kwargs):
        nonlocal enqueue_calls, competing_status
        enqueue_calls += 1
        competing = await client.post(retry_url, headers=_headers(USER_CONSULTANT))
        competing_status = competing.status_code
        return IngestStatus.processing.value

    monkeypatch.setattr(upload_session_recovery, "enqueue_ingest_processing", fake_enqueue)
    retried = await client.post(retry_url, headers=_headers(USER_CONSULTANT))

    assert retried.status_code == 200
    assert competing_status == 409
    assert enqueue_calls == 1
    await db_session.refresh(task)
    assert task.retry_count == 1


async def test_item_retry_treats_zero_byte_source_as_unavailable(client, db_session, monkeypatch):
    created = await client.post(
        "/api/v1/ingest/upload-sessions",
        headers=_headers(USER_CONSULTANT),
        files={"files": ("empty-on-disk.txt", b"initial body", "text/plain")},
    )
    assert created.status_code == 200
    session_id = created.json()["id"]
    item_id = created.json()["items"][0]["id"]
    item = await db_session.get(UploadSessionItem, uuid.UUID(item_id))
    task = await db_session.get(IngestTask, item.ingest_task_id)
    item.status = "failed"
    task.status = IngestStatus.failed.value
    task.processing_stage = "text_extraction_failed"
    client._kap_storage.resolve_path(task.source_file_ref).write_bytes(b"")
    await db_session.commit()

    enqueue_calls = 0

    async def fake_enqueue(*_args, **_kwargs):
        nonlocal enqueue_calls
        enqueue_calls += 1
        return IngestStatus.processing.value

    monkeypatch.setattr(upload_session_recovery, "enqueue_ingest_processing", fake_enqueue)
    retried = await client.post(
        f"/api/v1/ingest/upload-sessions/{session_id}/items/{item_id}/retry",
        headers=_headers(USER_CONSULTANT),
    )

    assert retried.status_code == 409
    assert retried.json()["detail"]["denied_reason"] == "upload_source_unavailable"
    assert enqueue_calls == 0

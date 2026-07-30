from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from starlette.datastructures import UploadFile

from app.api import ingest as ingest_api
from app.models.ingest import IngestTask, UploadSessionItem
from app.schemas.enums import IngestSource, IngestStatus
from app.seed.dev_seed import USER_CONSULTANT, USER_PROJECT_MANAGER
from app.services import upload_sessions
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

    monkeypatch.setattr(upload_sessions, "enqueue_ingest_processing", queued_without_worker)
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
    assert all(item["status"] == "processing" for item in body["items"][:200])
    assert all(item["status"] == "waiting" for item in body["items"][200:])

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
    for task in tasks:
        task.status = IngestStatus.pending_confirmation.value
        task.processing_stage = "awaiting_confirmation"
    await db_session.commit()

    advanced = await client.get(
        f"/api/v1/ingest/upload-sessions/{body['id']}",
        headers=_headers(USER_CONSULTANT),
    )
    assert advanced.status_code == 200
    next_body = advanced.json()
    assert next_body["current_batch_number"] == 2
    assert all(item["status"] == "awaiting_confirmation" for item in next_body["items"][:200])
    assert all(item["status"] == "processing" for item in next_body["items"][200:400])
    assert next_body["items"][400]["status"] == "waiting"


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

    monkeypatch.setattr(upload_sessions, "enqueue_ingest_processing", queued_without_worker)
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

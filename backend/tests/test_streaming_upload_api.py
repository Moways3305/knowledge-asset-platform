import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from app.seed.dev_seed import USER_ADMIN_ONLY, USER_CONSULTANT


async def _transport_request(client, kind, content=b"safe document text"):
    session_id = uuid.uuid4()
    headers = {"X-Dev-User-Id": str(USER_CONSULTANT)}
    initialized = await client.post(
        "/api/v1/ingest/upload-sessions/init",
        headers=headers,
        json={
            "session_id": str(session_id),
            "total_transport_batches": 1,
            "manifest": [
                {
                    "client_file_key": "a",
                    "file_name": "edge.txt",
                    "file_size": len(content),
                    "transport_batch_index": 0,
                }
            ],
        },
    )
    assert initialized.status_code == 200, initialized.text
    item_id = initialized.json()["items"][0]["id"]
    base = f"/api/v1/ingest/upload-sessions/{session_id}"
    if kind == "batch":
        return base + "/batches", {
            "headers": headers,
            "data": {"batch_id": "batch-0", "batch_index": "0", "item_ids": f'["{item_id}"]'},
            "files": {"files": ("edge.txt", content, "text/plain")},
        }
    return base + f"/items/{item_id}/bytes", {
        "headers": headers,
        "files": {"file": ("edge.txt", content, "text/plain")},
    }


@pytest.mark.parametrize("kind", ["batch", "replacement"])
@pytest.mark.parametrize("committed", [False, True])
async def test_transport_ambiguous_commit_retains_bytes(client, monkeypatch, kind, committed):
    url, kwargs = await _transport_request(client, kind)
    original = AsyncSession.commit

    async def ambiguous_commit(self):
        if committed:
            await original(self)
        raise TimeoutError("commit acknowledgement lost")

    monkeypatch.setattr(AsyncSession, "commit", ambiguous_commit)
    with pytest.raises(TimeoutError):
        await client.post(url, **kwargs)
    paths = list(client._kap_storage.root.rglob("edge.txt"))
    assert len(paths) == 1
    assert paths[0].read_bytes() == b"safe document text"


@pytest.mark.parametrize("kind", ["batch", "replacement"])
@pytest.mark.parametrize("error", [SQLAlchemyError("injected"), TimeoutError("flush timeout")])
async def test_transport_flush_failure_rolls_back_before_cleanup(client, monkeypatch, kind, error):
    url, kwargs = await _transport_request(client, kind)
    monkeypatch.setattr(AsyncSession, "flush", AsyncMock(side_effect=error))
    commit = AsyncMock(side_effect=AssertionError("must not commit failed attachment"))
    monkeypatch.setattr(AsyncSession, "commit", commit)
    with pytest.raises(type(error)):
        await client.post(url, **kwargs)
    commit.assert_not_called()
    assert not list(client._kap_storage.root.rglob("edge.txt"))


@pytest.mark.parametrize("kind", ["batch", "replacement"])
async def test_transport_rejects_empty_file(client, kind):
    url, kwargs = await _transport_request(client, kind, b"")
    response = await client.post(url, **kwargs)
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["denied_reason"] == "empty_file"
    assert not list(client._kap_storage.root.rglob("edge.txt"))


async def test_replacement_retry_does_not_read_or_store_again(client, monkeypatch):
    url, kwargs = await _transport_request(client, "replacement")
    first = await client.post(url, **kwargs)
    assert first.status_code == 200, first.text
    read = AsyncMock(side_effect=AssertionError("already received"))
    monkeypatch.setattr(UploadFile, "read", read)
    repeated = await client.post(url, **kwargs)
    assert repeated.status_code == 200, repeated.text
    read.assert_not_called()
    assert len(list(client._kap_storage.root.rglob("edge.txt"))) == 1


@pytest.mark.parametrize("kind", ["batch", "replacement"])
@pytest.mark.parametrize("cancel_during_copy", [False, True])
async def test_transport_copy_has_no_transaction_and_rechecks_after_copy(
    client, monkeypatch, kind, cancel_during_copy
):
    from app.services import upload_transport

    url, kwargs = await _transport_request(client, kind)
    original_load = upload_transport._load_owned_session
    original_read = UploadFile.read
    loads = []
    read_started = False

    async def tracked_load(session, caller, session_id, *, lock=False):
        loads.append((session, lock))
        return await original_load(session, caller, session_id, lock=lock)

    async def checked_read(self, size=-1):
        nonlocal read_started
        assert loads
        assert loads[0][1] is False
        assert not loads[0][0].in_transaction()
        if not read_started:
            read_started = True
            if cancel_during_copy:
                base = url.split("/items/")[0] if kind == "replacement" else url.rsplit("/", 1)[0]
                cancelled = await client.post(base + "/cancel", headers=kwargs["headers"])
                assert cancelled.status_code == 200, cancelled.text
        return await original_read(self, size)

    monkeypatch.setattr(upload_transport, "_load_owned_session", tracked_load)
    monkeypatch.setattr(UploadFile, "read", checked_read)
    response = await client.post(url, **kwargs)
    assert read_started
    assert [lock for _, lock in loads] == [False, True]
    if cancel_during_copy:
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["denied_reason"] == "upload_session_cancelled"
        assert not list(client._kap_storage.root.rglob("edge.txt"))
    else:
        assert response.status_code == 200, response.text
        assert len(list(client._kap_storage.root.rglob("edge.txt"))) == 1


@pytest.mark.parametrize("invalid", ["permission", "owner", "item", "cancelled"])
async def test_replacement_preflight_before_read(client, monkeypatch, invalid):
    from app.seed.dev_seed import USER_PROJECT_MANAGER

    url, kwargs = await _transport_request(client, "replacement")
    if invalid == "permission":
        kwargs["headers"] = {"X-Dev-User-Id": str(USER_ADMIN_ONLY)}
    elif invalid == "owner":
        kwargs["headers"] = {"X-Dev-User-Id": str(USER_PROJECT_MANAGER)}
    elif invalid == "item":
        url = url.rsplit("/items/", 1)[0] + f"/items/{uuid.uuid4()}/bytes"
    else:
        base = url.rsplit("/items/", 1)[0]
        response = await client.post(base + "/cancel", headers=kwargs["headers"])
        assert response.status_code == 200, response.text
    read = AsyncMock(side_effect=AssertionError("must validate before read"))
    monkeypatch.setattr(UploadFile, "read", read)
    response = await client.post(url, **kwargs)
    assert response.status_code in {403, 404, 409}, response.text
    read.assert_not_called()
    assert not list(client._kap_storage.root.rglob("edge.txt"))


@pytest.mark.parametrize("endpoint,field", [("upload", "file"), ("upload-sessions", "files")])
async def test_legacy_upload_reads_bounded_chunks(client, monkeypatch, endpoint, field):
    original = UploadFile.read
    sizes = []

    async def bounded_read(self, size=-1):
        sizes.append(size)
        assert 0 < size <= 1024 * 1024
        return await original(self, size)

    monkeypatch.setattr(UploadFile, "read", bounded_read)
    response = await client.post(
        f"/api/v1/ingest/{endpoint}",
        headers={"X-Dev-User-Id": str(USER_CONSULTANT)},
        files={field: ("资料.txt", b"safe document text", "text/plain")},
    )
    assert response.status_code == 200, response.text
    assert len(sizes) >= 2


@pytest.mark.parametrize("endpoint,field", [("upload", "file"), ("upload-sessions", "files")])
async def test_denied_upload_does_not_read_or_store(client, monkeypatch, endpoint, field):
    read = AsyncMock(side_effect=AssertionError("must authorize first"))
    monkeypatch.setattr(UploadFile, "read", read)
    response = await client.post(
        f"/api/v1/ingest/{endpoint}",
        headers={"X-Dev-User-Id": str(USER_ADMIN_ONLY)},
        files={field: ("资料.txt", b"safe document text", "text/plain")},
    )
    assert response.status_code == 403
    read.assert_not_called()
    assert not list(client._kap_storage.root.rglob("*.txt"))


@pytest.mark.parametrize("endpoint,field", [("upload", "file"), ("upload-sessions", "files")])
async def test_flush_failure_cleans_uncommitted_files(
    client, db_session, monkeypatch, endpoint, field
):
    monkeypatch.setattr(AsyncSession, "flush", AsyncMock(side_effect=SQLAlchemyError("injected")))
    with pytest.raises(SQLAlchemyError):
        await client.post(
            f"/api/v1/ingest/{endpoint}",
            headers={"X-Dev-User-Id": str(USER_CONSULTANT)},
            files={field: ("资料.txt", b"safe document text", "text/plain")},
        )
    assert not list(client._kap_storage.root.rglob("*.txt"))

"""The user-visible 100 MB limit uses decimal bytes, independently of parsing limits."""

from __future__ import annotations

import uuid

import pytest

from app.seed.dev_seed import USER_CONSULTANT
from app.services.storage import MAX_UPLOAD_BYTES, LocalFileStorage, StorageError
from app.services.upload_session_types import SINGLE_FILE_MAX_BYTES, TRANSPORT_BATCH_MAX_BYTES


def test_storage_accepts_100_mb_and_rejects_next_byte(tmp_path):
    assert MAX_UPLOAD_BYTES == SINGLE_FILE_MAX_BYTES == 100_000_000
    assert TRANSPORT_BATCH_MAX_BYTES == 20 * 1024 * 1024
    storage = LocalFileStorage(tmp_path)
    content = b"x" * MAX_UPLOAD_BYTES
    ref = storage.save(content, original_name="large.doc")
    assert storage.inspect(ref).size == MAX_UPLOAD_BYTES
    with pytest.raises(StorageError):
        storage.save(content + b"x", original_name="too-large.doc")


@pytest.mark.parametrize("size,accepted", [(100_000_000, True), (100_000_001, False)])
async def test_manifest_limit_matches_storage(client, size, accepted):
    response = await client.post(
        "/api/v1/ingest/upload-sessions/init",
        headers={"X-Dev-User-Id": str(USER_CONSULTANT)},
        json={
            "session_id": str(uuid.uuid4()),
            "total_transport_batches": 1,
            "manifest": [
                {
                    "client_file_key": "large",
                    "file_name": "large.ppt",
                    "file_size": size,
                    "transport_batch_index": 0,
                }
            ],
        },
    )
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert (item["error_code"] is None) == accepted
    if not accepted:
        assert item["error_code"] == "file_too_large"

"""Preview resolves the published asset's exact original, independently of ingestion."""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.ingest import IngestTask
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetFileObject, KnowledgeAssetVersion
from app.models.preview import PreviewCredential
from app.seed.dev_seed import KA_PERSONAL, KA_PROJECT_ALPHA, USER_CONSULTANT


async def attach_original(client, session, asset, content, *, version_id=None):
    reference = client._kap_storage.save(content, original_name="publication.md")
    session.add(
        KnowledgeAssetFileObject(
            asset_id=asset.id,
            version_id=version_id or asset.current_version_id,
            file_variant="original",
            file_name="publication.md",
            file_mime_type="text/markdown",
            file_size=len(content),
            storage_ref=reference,
            file_hash=hashlib.sha256(content).hexdigest(),
            confidentiality_level=asset.confidentiality_level,
        )
    )
    await session.commit()


async def assert_preview_bytes(client, asset_id, content, *, user=USER_CONSULTANT):
    headers = {"X-Dev-User-Id": str(user)}
    issued = await client.post(f"/api/v1/knowledge/{asset_id}/preview", headers=headers)
    assert issued.status_code == 200, issued.text
    entry = await client.get(issued.json()["preview_entry_url"], headers=headers)
    assert entry.status_code == 200, entry.text
    body = entry.json()
    assert body["render_type"] == "markdown", body
    assert body["message"] is None
    assert body["file_url"].startswith("/api/v1/preview/")
    response = await client.get(body["file_url"])
    assert response.status_code == 200, response.text
    assert response.content == content
    for private in ("storage_ref", "source_file_ref", "internal://", "local://", "token_hash"):
        assert private not in entry.text
        assert private not in str(response.headers)
    return issued.json(), body


async def _add_source_task(client, session, asset, version_id, content, *, created_at):
    session.add(
        IngestTask(
            source="upload",
            source_file_ref=client._kap_storage.save(content, original_name="original.md"),
            source_file_name="original.md",
            source_file_mime_type="text/markdown",
            result_asset_id=asset.id,
            result_version_id=version_id,
            status="confirmed",
            created_at=created_at,
        )
    )
    await session.commit()


@pytest.mark.parametrize("source", ["file_object", "ingest_task"])
async def test_preview_credential_keeps_its_version_after_current_version_changes(
    client, db_session, source
):
    asset = await db_session.get(KnowledgeAsset, KA_PERSONAL)
    old_version = await db_session.get(KnowledgeAssetVersion, asset.current_version_id)
    content = b"# Original approved V1"
    now = datetime.now(timezone.utc)
    if source == "file_object":
        await attach_original(client, db_session, asset, content)
        await _add_source_task(
            client, db_session, asset, old_version.id, b"# Stale task", created_at=now
        )
    else:
        await _add_source_task(client, db_session, asset, old_version.id, content, created_at=now)
    issued, entry = await assert_preview_bytes(client, asset.id, content)

    old_version.version_status = "superseded"
    await db_session.flush()
    newer = KnowledgeAssetVersion(
        asset_id=asset.id,
        version_no="V2",
        version_status="active",
        created_by=USER_CONSULTANT,
    )
    db_session.add(newer)
    await db_session.flush()
    asset.current_version_id = newer.id
    await attach_original(client, db_session, asset, b"# Different V2")
    await _add_source_task(
        client,
        db_session,
        asset,
        newer.id,
        b"# Different V2",
        created_at=now + timedelta(seconds=1),
    )

    # The fetch URL already handed to the viewer cannot silently change its document.
    response = await client.get(entry["file_url"])
    assert response.status_code == 200, response.text
    assert response.content == content
    reopened = await client.get(
        issued["preview_entry_url"], headers={"X-Dev-User-Id": str(USER_CONSULTANT)}
    )
    assert reopened.status_code == 200, reopened.text
    response = await client.get(reopened.json()["file_url"])
    assert response.status_code == 200 and response.content == content


@pytest.mark.parametrize("multiple_versions", [False, True])
async def test_unversioned_legacy_ingest_is_only_usable_for_single_version_assets(
    client, db_session, multiple_versions
):
    asset = await db_session.get(KnowledgeAsset, KA_PERSONAL)
    content = b"# Legacy original"
    await _add_source_task(
        client, db_session, asset, None, content, created_at=datetime.now(timezone.utc)
    )
    if not multiple_versions:
        await assert_preview_bytes(client, asset.id, content)
        return
    db_session.add(
        KnowledgeAssetVersion(
            asset_id=asset.id,
            version_no="V2",
            version_status="draft",
            created_by=USER_CONSULTANT,
        )
    )
    await db_session.commit()
    headers = {"X-Dev-User-Id": str(USER_CONSULTANT)}
    issued = await client.post(f"/api/v1/knowledge/{asset.id}/preview", headers=headers)
    entry = await client.get(issued.json()["preview_entry_url"], headers=headers)
    assert entry.status_code == 200
    assert entry.json()["message"] == "preview_source_unavailable"
    assert entry.json()["file_url"] is None


async def test_inconsistent_credential_version_cannot_fall_back_to_legacy_original(
    client, db_session
):
    asset = await db_session.get(KnowledgeAsset, KA_PERSONAL)
    await _add_source_task(
        client, db_session, asset, None, b"# Legacy original", created_at=datetime.now(timezone.utc)
    )
    issued, entry = await assert_preview_bytes(client, asset.id, b"# Legacy original")
    other_asset = await db_session.get(KnowledgeAsset, KA_PROJECT_ALPHA)
    credential = await db_session.get(PreviewCredential, uuid.UUID(issued["credential_id"]))
    credential.target_version_id = other_asset.current_version_id
    await db_session.commit()
    response = await client.get(entry["file_url"])
    assert response.status_code == 404
    assert response.json()["detail"]["denied_reason"] == "preview_source_unavailable"


async def test_legacy_credential_without_version_uses_current_asset_original(client, db_session):
    asset = await db_session.get(KnowledgeAsset, KA_PERSONAL)
    content = b"# Current original"
    await attach_original(client, db_session, asset, content)
    issued, entry = await assert_preview_bytes(client, asset.id, content)
    credential = await db_session.get(PreviewCredential, uuid.UUID(issued["credential_id"]))
    credential.target_version_id = None
    await db_session.commit()
    response = await client.get(entry["file_url"])
    assert response.status_code == 200 and response.content == content


@pytest.mark.parametrize("reference", ["internal://missing.md", "invalid://private-storage-path"])
async def test_unreadable_original_file_object_returns_safe_not_found(
    client, db_session, reference
):
    asset = await db_session.get(KnowledgeAsset, KA_PERSONAL)
    content = b"# Stored original"
    await attach_original(client, db_session, asset, content)
    _, entry = await assert_preview_bytes(client, asset.id, content)
    original = await db_session.scalar(
        select(KnowledgeAssetFileObject).where(
            KnowledgeAssetFileObject.asset_id == asset.id,
            KnowledgeAssetFileObject.file_variant == "original",
        )
    )
    original.storage_ref = reference
    await db_session.commit()
    response = await client.get(entry["file_url"])
    assert response.status_code == 404
    assert response.json()["detail"]["denied_reason"] == "preview_source_unavailable"
    assert reference not in response.text

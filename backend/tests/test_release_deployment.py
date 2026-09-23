"""Deployment proof, immutable provenance and automated draft regression tests."""

import httpx
import pytest
from sqlalchemy import func, select
from test_release_notes import ADMIN, API, MANAGE, USER, create, payload, publish

from app.core import release_manifest
from app.core.config import Settings
from app.core.release_manifest import ReleaseManifest
from app.models.audit import AuditEvent
from app.models.release_note import ReleaseNote
from app.services.release_deployment import (
    check_release_identity,
    record_deployment,
    verify_deployment,
)


def manifest(**overrides):
    return ReleaseManifest.model_validate(
        {**payload(), "commit": "a" * 40, "previous_commit": "b" * 40, **overrides}
    )


async def test_sync_creates_private_draft_and_is_idempotent_after_edit_and_publish(
    client, db_session
):
    release = manifest()
    note = await record_deployment(db_session, release)
    note_id, deployed_at = note.id, note.deployed_at
    assert note.created_by is None
    assert note.published_at is None
    assert (await client.get(API, headers=USER)).json()["total"] == 0
    assert (await client.get(API + "/status", headers=USER)).json()["unread_count"] == 0
    listing = (await client.get(MANAGE, headers=ADMIN)).json()["items"][0]
    assert listing["source_commit"] == release.commit and listing["deployed_at"]
    edited = await client.put(
        f"{MANAGE}/{note_id}", headers=ADMIN, json={**payload(title="人工修订"), "revision": 1}
    )
    assert edited.status_code == 200
    again = await record_deployment(db_session, release)
    assert again.title == "人工修订" and again.revision == 2
    assert (await publish(client, edited.json())).status_code == 200
    again = await record_deployment(db_session, release)
    assert again.published_at and again.deployed_at.replace(tzinfo=None) == deployed_at.replace(
        tzinfo=None
    )
    assert await db_session.scalar(select(func.count()).select_from(ReleaseNote)) == 1
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "release_note.deployment_verified")
        )
        == 1
    )
    assert (await client.get(API + "/status", headers=USER)).json()["unread_count"] == 1


async def test_unverified_manual_note_cannot_publish_or_forge_proof(client):
    note = await create(client)
    assert (await publish(client, note)).status_code == 409
    forged = await client.post(
        MANAGE,
        headers=ADMIN,
        json={**payload("2.0.0"), "source_commit": "a" * 40, "deployed_at": "2026-01-01T00:00:00Z"},
    )
    assert forged.status_code == 422


async def test_bind_existing_draft_keeps_content_and_invalidates_stale_editor(client, db_session):
    draft = await create(client, title="预先编写的内容", notify_users=False)
    note = await record_deployment(db_session, manifest())
    assert str(note.id) == draft["id"] and note.title == draft["title"]
    assert note.revision == 2 and note.notify_users is False
    assert (await publish(client, draft)).status_code == 409
    renamed = await client.put(
        f"{MANAGE}/{note.id}", headers=ADMIN, json={**payload("2.0.0"), "revision": 2}
    )
    assert renamed.status_code == 409


@pytest.mark.parametrize(
    "change", [{"commit": "c" * 40}, {"title": "不同清单"}, {"version": "2.0.0"}]
)
async def test_conflicting_version_commit_or_manifest_is_rejected(db_session, change):
    await record_deployment(db_session, manifest())
    with pytest.raises(ValueError):
        await check_release_identity(db_session, manifest(**change))
    with pytest.raises(ValueError):
        await record_deployment(db_session, manifest(**change))
    await db_session.rollback()
    assert await db_session.scalar(select(func.count()).select_from(ReleaseNote)) == 1


async def test_identity_preflight_does_not_create_a_draft(db_session):
    await check_release_identity(db_session, manifest())
    assert await db_session.scalar(select(func.count()).select_from(ReleaseNote)) == 0
    await record_deployment(db_session, manifest())
    await check_release_identity(db_session, manifest())
    assert await db_session.scalar(select(func.count()).select_from(ReleaseNote)) == 1


async def test_cli_probe_failure_never_opens_a_write_session(monkeypatch):
    from unittest.mock import AsyncMock, Mock

    from app.commands import sync_release_notes

    monkeypatch.setattr(sync_release_notes, "load_manifest", manifest)
    monkeypatch.setattr(
        sync_release_notes, "verify_deployment", AsyncMock(side_effect=ValueError("探测失败"))
    )
    sessions = Mock()
    monkeypatch.setattr(sync_release_notes, "get_sessionmaker", sessions)
    with pytest.raises(ValueError, match="探测失败"):
        await sync_release_notes.run("https://kap.example.test")
    sessions.assert_not_called()


async def test_published_legacy_note_is_not_relabelled_as_verified(client, db_session):
    draft = await create(client)
    note = await db_session.scalar(select(ReleaseNote))
    from app.db.utils import utc_now

    note.published_at = utc_now()
    await db_session.commit()
    with pytest.raises(ValueError, match="历史公告"):
        await record_deployment(db_session, manifest())
    assert (await client.get(API, headers=USER)).json()["items"][0]["id"] == draft["id"]


@pytest.mark.parametrize(
    "failure", [None, "frontend", "backend", "ready", "config", "local", "missing", "redirect"]
)
async def test_deployment_requires_matching_live_frontend_backend_and_production_health(failure):
    release = manifest()
    identity = {"version": release.version, "commit": release.commit}
    responses = {
        "/release-identity.json": identity,
        "/health/release": identity,
        "/health/ready": {"status": "ready"},
        "/health/config": {"production_blockers": [], "production_ready": True},
    }
    if failure == "frontend":
        responses["/release-identity.json"] = {**identity, "commit": "c" * 40}
    if failure == "backend":
        responses["/health/release"] = {**identity, "version": "v9.0.0"}
    if failure == "ready":
        responses["/health/ready"] = {"status": "not_ready"}
    if failure == "config":
        responses["/health/config"] = {
            "production_blockers": ["SECRET_MISSING"],
            "production_ready": False,
        }
    if failure == "local":
        responses["/health/config"] = {"production_blockers": [], "production_ready": False}

    def transport(request):
        status = 404 if failure == "missing" else 302 if failure == "redirect" else 200
        return httpx.Response(status, json=responses[request.url.path])

    async with httpx.AsyncClient(
        base_url="https://kap.example.test", transport=httpx.MockTransport(transport)
    ) as client:
        if failure:
            with pytest.raises((ValueError, httpx.HTTPStatusError)):
                await verify_deployment(client, release)
        else:
            await verify_deployment(client, release)


def test_baked_manifest_is_authoritative_and_invalid_manifest_fails_closed(tmp_path, monkeypatch):
    path = tmp_path / "release-manifest.json"
    monkeypatch.setattr(release_manifest, "MANIFEST_PATH", path)
    assert Settings(app_version="0.2.0").app_version == "0.2.0"
    path.write_text(manifest().model_dump_json(), encoding="utf-8")
    assert Settings(app_version="0.2.0").app_version == "1.0.0"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        Settings()


async def test_health_identity_exposes_no_draft_text(client, tmp_path, monkeypatch):
    path = tmp_path / "release-manifest.json"
    path.write_text(manifest().model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(release_manifest, "MANIFEST_PATH", path)
    response = await client.get("/health/release")
    assert response.json() == {"version": "v1.0.0", "commit": "a" * 40}

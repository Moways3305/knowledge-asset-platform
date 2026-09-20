"""Authorization, publishing races, read isolation, and release metadata contracts."""

import uuid

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.models.audit import AuditEvent
from app.models.identity import User
from app.models.release_note import ReleaseNoteRead
from app.seed.dev_seed import USER_ADMIN_ONLY, USER_BOSS, USER_CONSULTANT, USER_DIRECTOR

ADMIN = {"X-Dev-User-Id": str(USER_ADMIN_ONLY)}
USER = {"X-Dev-User-Id": str(USER_CONSULTANT)}
API = "/api/v1/release-notes"
MANAGE = "/api/v1/admin/release-notes"


def payload(version="1.0.0", **kwargs):
    return {
        "version": version,
        "title": "上传体验更新",
        "entries": [{"kind": "fixed", "text": "修复人工主题同步"}],
        "notify_users": True,
        **kwargs,
    }


async def create(client, **kwargs):
    response = await client.post(MANAGE, headers=ADMIN, json=payload(**kwargs))
    assert response.status_code == 201, response.text
    return response.json()


async def publish(client, note):
    return await client.post(
        f"{MANAGE}/{note['id']}/publish", headers=ADMIN, json={"revision": note["revision"]}
    )


@pytest.mark.parametrize("user", [USER_CONSULTANT, USER_BOSS, USER_DIRECTOR])
async def test_only_active_admin_can_manage(client, user):
    note = await create(client)
    headers = {"X-Dev-User-Id": str(user)}
    assert (await client.get(MANAGE, headers=headers)).status_code == 403
    assert (await client.post(MANAGE, headers=headers, json=payload("2.0.0"))).status_code == 403
    assert (
        await client.put(
            f"{MANAGE}/{note['id']}", headers=headers, json={**payload(), "revision": 1}
        )
    ).status_code == 403
    assert (
        await client.post(f"{MANAGE}/{note['id']}/publish", headers=headers, json={"revision": 1})
    ).status_code == 403


async def test_drafts_never_leak_and_publish_is_audited(client, db_session):
    note = await create(client)
    assert note["version"] == "v1.0.0"
    assert (await client.get(API, headers=USER)).json()["items"] == []
    assert (await client.get(API + "?state=draft", headers=USER)).json()["total"] == 0
    assert (await client.get(API + "/status", headers=USER)).json()["unread_count"] == 0
    response = await publish(client, note)
    assert response.status_code == 200, response.text
    published = response.json()
    assert published["revision"] == 2 and published["published_at"]
    listing = (await client.get(API, headers=USER)).json()
    assert listing["items"][0]["is_unread"] is True
    assert "created_by" not in listing["items"][0]
    assert (await client.get(MANAGE + "?state=draft", headers=ADMIN)).json()["total"] == 0
    assert (await client.get(MANAGE + "?state=published", headers=ADMIN)).json()["total"] == 1
    events = (
        await db_session.scalars(select(AuditEvent).where(AuditEvent.target_type == "release_note"))
    ).all()
    assert {event.action for event in events} == {"release_note.created", "release_note.published"}
    assert all(event.actor_user_id == USER_ADMIN_ONLY for event in events)


async def test_stale_editor_and_double_publish_cannot_overwrite(client):
    note = await create(client)
    updated = await client.put(
        f"{MANAGE}/{note['id']}", headers=ADMIN, json={**payload(title="已修订"), "revision": 1}
    )
    assert updated.status_code == 200
    stale = await publish(client, note)
    assert stale.status_code == 409
    assert "重新加载" in stale.json()["detail"]["message"]
    assert (
        await client.put(
            f"{MANAGE}/{note['id']}",
            headers=ADMIN,
            json={**payload(title="过期覆盖"), "revision": 1},
        )
    ).status_code == 409
    assert (await publish(client, updated.json())).status_code == 200
    assert (await publish(client, updated.json())).status_code == 409
    assert (
        await client.put(f"{MANAGE}/{note['id']}", headers=ADMIN, json={**payload(), "revision": 3})
    ).status_code == 409
    assert (await client.get(API, headers=USER)).json()["items"][0]["title"] == "已修订"


async def test_read_receipts_are_account_scoped_idempotent_and_only_for_published_ids(
    client, db_session
):
    first = await create(client)
    second = await create(client, version="1.1.0")
    draft = await create(client, version="1.2.0")
    await publish(client, first)
    await publish(client, second)
    ids = [first["id"], first["id"], draft["id"], str(uuid.uuid4())]
    for _ in range(2):
        response = await client.post(API + "/read", headers=USER, json={"release_ids": ids})
        assert response.status_code == 200
        assert response.json()["unread_count"] == 1
    assert (await client.get(API + "/status", headers=ADMIN)).json()["unread_count"] == 2
    assert await db_session.scalar(select(func.count()).select_from(ReleaseNoteRead)) == 1
    assert (await publish(client, draft)).status_code == 200
    assert (await client.get(API + "/status", headers=USER)).json()["unread_count"] == 2


async def test_silent_release_visible_without_unread_and_does_not_change_running_version(
    client, monkeypatch
):
    monkeypatch.setattr(get_settings(), "app_version", "0.9.3")
    note = await create(client, notify_users=False)
    await publish(client, note)
    assert (await client.get(API, headers=USER)).json()["items"][0]["is_unread"] is False
    assert (await client.get(API + "/status", headers=USER)).json() == {
        "running_version": "0.9.3",
        "unread_count": 0,
    }


async def test_duplicate_versions_and_empty_publish(client):
    note = await create(client, entries=[])
    assert (await publish(client, note)).status_code == 422
    assert (await client.post(MANAGE, headers=ADMIN, json=payload("v1.0.0"))).status_code == 409
    other = await create(client, version="2.0.0")
    assert (
        await client.put(
            f"{MANAGE}/{other['id']}", headers=ADMIN, json={**payload(), "revision": 1}
        )
    ).status_code == 409


@pytest.mark.parametrize(
    "change",
    [
        {"title": "   "},
        {"version": "whatever"},
        {"entries": [{"kind": "raw", "text": "x"}]},
        {"entries": [{"kind": "new", "text": "  "}]},
        {"entries": [{"kind": "new", "text": "x"}] * 51},
    ],
)
async def test_invalid_content_rejected(client, change):
    assert (await client.post(MANAGE, headers=ADMIN, json=payload(**change))).status_code == 422


async def test_list_pagination_is_bounded_and_sorted_by_publication(client):
    for i in range(3):
        await publish(client, await create(client, version=f"1.0.{i}"))
    response = (await client.get(API + "?page=2&page_size=2", headers=USER)).json()
    assert response["total"] == 3 and len(response["items"]) == 1
    assert response["items"][0]["version"] == "v1.0.0"
    assert (await client.get(API + "?page_size=500", headers=USER)).status_code == 422


async def test_inactive_account_cannot_read_or_manage(client, db_session):
    user = await db_session.get(User, USER_ADMIN_ONLY)
    user.status = "inactive"
    await db_session.commit()
    assert (await client.get(API, headers=ADMIN)).status_code in {401, 403}
    assert (await client.post(MANAGE, headers=ADMIN, json=payload())).status_code in {401, 403}


async def test_cookie_publish_requires_csrf_and_valid_token_succeeds(client):
    login = await client.post("/api/v1/auth/login", json={"email": "admin.e@dev.local"})
    assert login.status_code == 200
    assert (await client.post(MANAGE, json=payload())).status_code == 403
    token = (await client.get("/api/v1/auth/csrf")).json()["csrf_token"]
    headers = {"X-CSRF-Token": token}
    created = await client.post(MANAGE, headers=headers, json=payload())
    assert created.status_code == 201, created.text
    note = created.json()
    path = f"{MANAGE}/{note['id']}/publish"
    assert (await client.post(path, json={"revision": 1})).status_code == 403
    assert (await client.post(path, headers=headers, json={"revision": 1})).status_code == 200

"""Directory editors must save and publish the exact draft they reviewed."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.models.audit import AuditEvent
from app.models.naming import NamingRuleRevision
from app.seed.dev_seed import USER_BOSS

HEADERS = {"X-Dev-User-Id": str(USER_BOSS)}
ROOT = "/api/v1/admin/naming-rules"


async def _center(client):
    response = await client.get(ROOT, headers=HEADERS)
    assert response.status_code == 200, response.text
    return response.json()


def _baseline(center):
    return {
        "expected_base_version": center["published"]["version"],
        "expected_draft_updated_at": center["draft"]["updated_at"],
    }


@pytest.mark.parametrize("action", ["save", "publish"])
async def test_stale_directory_page_cannot_overwrite_or_publish_newer_draft(
    client, db_session, action
):
    first_page = await _center(client)
    old_page = await _center(client)
    directories = deepcopy(first_page["draft"]["config"]["directories"])
    directories[0]["display_name"] = "新的目录名称"
    saved = await client.put(
        f"{ROOT}/draft",
        headers=HEADERS,
        json={**_baseline(first_page), "directories": directories},
    )
    assert saved.status_code == 200, saved.text
    audit_count = await db_session.scalar(select(func.count()).select_from(AuditEvent))

    if action == "save":
        stale = await client.put(
            f"{ROOT}/draft",
            headers=HEADERS,
            json={
                **_baseline(old_page),
                "directories": old_page["draft"]["config"]["directories"],
            },
        )
    else:
        stale = await client.post(f"{ROOT}/publish", headers=HEADERS, json=_baseline(old_page))

    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"]["denied_reason"] == "naming_rule_draft_conflict"
    current = await _center(client)
    assert current["published"] == first_page["published"]
    assert current["draft"] == saved.json()
    assert await db_session.scalar(select(func.count()).select_from(AuditEvent)) == audit_count
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(NamingRuleRevision)
            .where(NamingRuleRevision.status == "draft")
        )
        == 1
    )


@pytest.mark.parametrize("action", ["save", "publish"])
@pytest.mark.parametrize("stamp", ["missing", None])
async def test_directory_mutations_require_draft_stamp(client, action, stamp):
    center = await _center(client)
    body = {"expected_base_version": center["published"]["version"]}
    if stamp is None:
        body["expected_draft_updated_at"] = None
    if action == "save":
        body["directories"] = center["draft"]["config"]["directories"]
        response = await client.put(f"{ROOT}/draft", headers=HEADERS, json=body)
    else:
        response = await client.post(f"{ROOT}/publish", headers=HEADERS, json=body)
    assert response.status_code == 422, response.text
    assert await _center(client) == center


async def test_returned_stamp_allows_next_save_and_publish_but_not_old_published_version(client):
    center = await _center(client)
    original = deepcopy(center)
    for name in ("第一次修改", "再次核对的修改"):
        directories = deepcopy(center["draft"]["config"]["directories"])
        directories[0]["display_name"] = name
        saved = await client.put(
            f"{ROOT}/draft",
            headers=HEADERS,
            json={**_baseline(center), "directories": directories},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["updated_at"] != center["draft"]["updated_at"]
        center["draft"] = saved.json()
    published = await client.post(f"{ROOT}/publish", headers=HEADERS, json=_baseline(center))
    assert published.status_code == 200, published.text
    current = published.json()
    assert current["published"]["config"] == center["draft"]["config"]
    assert current["published"]["version"] == center["draft"]["version"]
    assert current["draft"]["version"] == center["draft"]["version"] + 1
    current = await _center(client)
    for action in ("save", "publish"):
        # Even a current draft stamp cannot bypass an obsolete formal version.
        body = {**_baseline(original), "expected_draft_updated_at": current["draft"]["updated_at"]}
        if action == "save":
            body["directories"] = original["draft"]["config"]["directories"]
            stale = await client.put(f"{ROOT}/draft", headers=HEADERS, json=body)
        else:
            stale = await client.post(f"{ROOT}/publish", headers=HEADERS, json=body)
        assert stale.status_code == 409
        assert stale.json()["detail"]["denied_reason"] == "naming_rule_publish_conflict"
    assert await _center(client) == current


@pytest.mark.parametrize("microsecond_offset", [0, 1])
@pytest.mark.parametrize("action", ["save", "publish"])
async def test_draft_stamp_preserves_microseconds_and_accepts_equal_timezone(
    client, db_session, action, microsecond_offset
):
    await _center(client)
    draft = await db_session.scalar(
        select(NamingRuleRevision).where(NamingRuleRevision.status == "draft")
    )
    fixed = datetime(2026, 10, 23, 1, 2, 3, 123456, tzinfo=timezone.utc)
    draft.updated_at = fixed
    await db_session.commit()
    center = await _center(client)
    expected = (fixed + timedelta(microseconds=microsecond_offset)).astimezone(
        timezone(timedelta(hours=8))
    )
    body = {**_baseline(center), "expected_draft_updated_at": expected.isoformat()}
    if action == "save":
        body["directories"] = center["draft"]["config"]["directories"]
        response = await client.put(f"{ROOT}/draft", headers=HEADERS, json=body)
    else:
        response = await client.post(f"{ROOT}/publish", headers=HEADERS, json=body)
    assert response.status_code == (409 if microsecond_offset else 200), response.text


async def test_noop_save_advances_stamp_even_when_clock_does_not_advance(client, db_session):
    await _center(client)
    draft = await db_session.scalar(
        select(NamingRuleRevision).where(NamingRuleRevision.status == "draft")
    )
    draft.updated_at = datetime(2099, 1, 1, tzinfo=timezone.utc)
    await db_session.commit()
    center = await _center(client)
    saved = await client.put(
        f"{ROOT}/draft",
        headers=HEADERS,
        json={**_baseline(center), "directories": center["draft"]["config"]["directories"]},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["updated_at"].startswith("2099-01-01T00:00:00.000001")

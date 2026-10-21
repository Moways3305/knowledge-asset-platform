"""Grant management stays within current visibility and existing revocation authority."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from test_original_access_api import _assert_no_leak, _hdr, _mk_asset

from app.db.utils import utc_now
from app.models.identity import ProjectMember
from app.models.knowledge import KnowledgeAsset
from app.models.original_access import AccessGrant
from app.seed.dev_seed import (
    PROJECT_ALPHA,
    PROJECT_BETA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
    USER_PROJECT_MANAGER,
)

BASE = "/api/v1/original-access/grants"


async def grant(session, **kwargs):
    asset_id = await _mk_asset(session, **kwargs)
    row = AccessGrant(
        asset_id=asset_id,
        grantee_user_id=USER_CONSULTANT,
        granted_by_user_id=USER_BOSS,
        expires_at=utc_now() + timedelta(days=7),
    )
    session.add(row)
    await session.commit()
    return row


async def test_history_and_revocation_close_the_loop(client, db_session):
    row = await grant(db_session)
    response = await client.get(BASE, headers=_hdr(USER_CONSULTANT))
    assert response.status_code == 200
    assert response.json()["total"] == 1
    item = response.json()["items"][0]
    assert item["grant_id"] == str(row.id) and item["can_revoke"]
    assert item["status"] == "active" and item["grantee_name"]
    _assert_no_leak(response.text)
    revoked = await client.post(
        f"{BASE}/{row.id}/revoke",
        headers=_hdr(USER_BOSS),
        json={"reason": "验收授权结束"},
    )
    assert revoked.status_code == 200
    history = await client.get(BASE + "?status=revoked", headers=_hdr(USER_CONSULTANT))
    item = history.json()["items"][0]
    assert item["status"] == "revoked" and not item["can_revoke"]
    assert item["revoke_reason"] == "验收授权结束" and item["revoked_by_name"]
    assert (await client.get(BASE + "?status=active", headers=_hdr(USER_BOSS))).json()["total"] == 0
    assert (
        await client.post(
            f"{BASE}/{row.id}/revoke",
            headers=_hdr(USER_BOSS),
            json={},
        )
    ).status_code == 409


@pytest.mark.parametrize(
    "actor,scope,project,level,visible",
    [
        (USER_BOSS, "company", None, "L3", True),
        (USER_DIRECTOR, "company", None, "L3", True),
        (USER_PROJECT_MANAGER, "company", None, "L3", False),
        (USER_CONSULTANT, "company", None, "L3", True),
        (USER_PROJECT_MANAGER, "project", PROJECT_ALPHA, "L3", True),
        (USER_PROJECT_MANAGER, "project", PROJECT_BETA, "L3", False),
        (USER_DIRECTOR, "project", PROJECT_BETA, "L5", False),
        (USER_CONSULTANT, "personal", None, "L3", False),
    ],
)
async def test_current_scope_before_totals_and_pagination(
    client,
    db_session,
    actor,
    scope,
    project,
    level,
    visible,
):
    row = await grant(db_session, scope=scope, project_id=project, level=level)
    response = await client.get(BASE + "?limit=1", headers=_hdr(actor))
    assert response.status_code == 200
    assert response.json()["total"] == int(visible)
    assert len(response.json()["items"]) == int(visible)
    if visible:
        assert response.json()["items"][0]["can_revoke"]
        assert (
            await client.post(
                f"{BASE}/{row.id}/revoke",
                headers=_hdr(actor),
                json={"reason": "结束测试授权"},
            )
        ).status_code == 200
    else:
        assert str(row.id) not in response.text
    _assert_no_leak(response.text)


async def test_invisible_rows_never_use_page_slots_or_totals(client, db_session):
    visible = await grant(db_session)
    for _ in range(3):
        hidden = await grant(db_session)
        hidden.grantee_user_id = USER_DIRECTOR
    await db_session.commit()
    response = await client.get(BASE + "?limit=1", headers=_hdr(USER_CONSULTANT))
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["grant_id"] == str(visible.id)
    assert (await client.get(BASE + "?limit=1&offset=1", headers=_hdr(USER_CONSULTANT))).json()[
        "items"
    ] == []


async def test_expired_history_is_read_only_and_cannot_be_revoked(client, db_session):
    row = await grant(db_session)
    row.expires_at = utc_now() - timedelta(seconds=1)
    await db_session.commit()
    response = await client.get(BASE + "?status=expired", headers=_hdr(USER_BOSS))
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["status"] == "expired"
    assert not response.json()["items"][0]["can_revoke"]
    await db_session.refresh(row)
    assert row.status == "active"  # History projection never mutates persistence.
    assert (
        await client.post(f"{BASE}/{row.id}/revoke", headers=_hdr(USER_BOSS), json={})
    ).status_code == 409


async def test_admin_business_boundary_and_live_membership(client, db_session):
    row = await grant(db_session, scope="project", project_id=PROJECT_ALPHA)
    assert (await client.get(BASE, headers=_hdr(USER_ADMIN_ONLY))).status_code == 403
    assert (
        await client.post(f"{BASE}/{row.id}/revoke", headers=_hdr(USER_ADMIN_ONLY), json={})
    ).status_code == 403
    member = await db_session.scalar(
        select(ProjectMember).where(
            ProjectMember.user_id == USER_PROJECT_MANAGER,
            ProjectMember.project_id == PROJECT_ALPHA,
        )
    )
    assert member is not None
    member.status = "inactive"
    await db_session.commit()
    assert (await client.get(BASE, headers=_hdr(USER_PROJECT_MANAGER))).json()["total"] == 0
    assert (
        await client.post(f"{BASE}/{row.id}/revoke", headers=_hdr(USER_PROJECT_MANAGER), json={})
    ).status_code == 403
    await db_session.refresh(row)
    assert row.status == "active"


async def test_original_issuer_retains_existing_revocation_authority(client, db_session):
    row = await grant(db_session)
    row.grantee_user_id = USER_DIRECTOR
    row.granted_by_user_id = USER_PROJECT_MANAGER
    await db_session.commit()
    response = await client.get(BASE, headers=_hdr(USER_PROJECT_MANAGER))
    assert response.json()["items"][0]["can_revoke"]
    assert (
        await client.post(f"{BASE}/{row.id}/revoke", headers=_hdr(USER_PROJECT_MANAGER), json={})
    ).status_code == 200


async def test_history_rechecks_classification_and_ownership(client, db_session):
    row = await grant(db_session)
    asset = await db_session.get(KnowledgeAsset, row.asset_id)
    asset.confidentiality_level = "L5"
    await db_session.commit()
    assert (await client.get(BASE, headers=_hdr(USER_CONSULTANT))).json()["total"] == 0
    asset.scope = "personal"
    await db_session.commit()
    assert (await client.get(BASE, headers=_hdr(USER_BOSS))).json()["total"] == 0
    asset.owner_user_id = USER_CONSULTANT
    asset.asset_status = "archived"
    await db_session.commit()
    assert (await client.get(BASE, headers=_hdr(USER_CONSULTANT))).json()["total"] == 1


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1", "status=unknown"])
async def test_history_rejects_unbounded_or_unknown_query(client, query):
    assert (await client.get(BASE + "?" + query, headers=_hdr(USER_BOSS))).status_code == 422


async def test_unknown_grant_is_not_replaced_by_another_record(client):
    assert (
        await client.post(f"{BASE}/{uuid.uuid4()}/revoke", headers=_hdr(USER_BOSS), json={})
    ).status_code == 404


async def test_admin_with_project_role_still_has_no_business_revocation(client, db_session):
    row = await grant(db_session, scope="project", project_id=PROJECT_ALPHA)
    db_session.add(
        ProjectMember(
            project_id=PROJECT_ALPHA,
            user_id=USER_ADMIN_ONLY,
            project_role="project_manager",
            status="active",
        )
    )
    await db_session.commit()
    assert (await client.get(BASE, headers=_hdr(USER_ADMIN_ONLY))).status_code == 403
    assert (
        await client.post(f"{BASE}/{row.id}/revoke", headers=_hdr(USER_ADMIN_ONLY), json={})
    ).status_code == 403
    await db_session.refresh(row)
    assert row.status == "active"


async def test_revoke_reason_is_bounded_and_sanitized(client, db_session):
    row = await grant(db_session)
    assert (
        await client.post(
            f"{BASE}/{row.id}/revoke", headers=_hdr(USER_BOSS), json={"reason": "x" * 1001}
        )
    ).status_code == 422
    assert (
        await client.post(
            f"{BASE}/{row.id}/revoke",
            headers=_hdr(USER_BOSS),
            json={"reason": "storage_ref=s3://secret"},
        )
    ).status_code == 200
    response = await client.get(BASE, headers=_hdr(USER_BOSS))
    _assert_no_leak(response.text)
    assert response.json()["items"][0]["revoke_reason"] == "[redacted]"


async def test_history_sanitizes_legacy_reason_without_rewriting_it(client, db_session):
    row = await grant(db_session)
    row.status = "revoked"
    row.revoke_reason = "storage_ref=s3://secret"
    await db_session.commit()
    response = await client.get(BASE, headers=_hdr(USER_BOSS))
    _assert_no_leak(response.text)
    assert response.json()["items"][0]["revoke_reason"] == "[redacted]"
    await db_session.refresh(row)
    assert row.revoke_reason == "storage_ref=s3://secret"

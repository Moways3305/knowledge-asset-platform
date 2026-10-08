"""Knowledge trust loop regression tests, independent of existing governance suites."""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.utils import utc_now
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.notification import BusinessNotification
from app.seed.dev_seed import (
    KA_COMPANY_L2,
    KA_PERSONAL,
    KA_PROJECT_ALPHA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
    USER_PROJECT_MANAGER,
)
from app.services.knowledge_review import scan_due_reviews, stamp


def headers(user):
    return {"X-Dev-User-Id": str(user)}


async def state(client, asset=KA_COMPANY_L2, user=USER_BOSS):
    response = await client.get(f"/api/v1/knowledge/{asset}/trust", headers=headers(user))
    assert response.status_code == 200, response.text
    return response.json()


async def command(client, action, data, *, asset=KA_COMPANY_L2, user=USER_BOSS):
    body = {
        "expected_updated_at": (await state(client, asset, user))["updated_at"],
        "reason": "核查并修订",
        **data,
    }
    method = client.patch if action == "policy" else client.post
    return await method(
        f"/api/v1/knowledge/{asset}/trust/{action}", headers=headers(user), json=body
    )


async def policy(client, asset=KA_COMPANY_L2, user=USER_BOSS):
    response = await command(
        client,
        "policy",
        {
            "maintainer_user_id": str(user),
            "review_due_at": (utc_now() + timedelta(days=30)).isoformat(),
        },
        asset=asset,
        user=user,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def verify(client, asset=KA_COMPANY_L2, user=USER_BOSS):
    response = await command(
        client,
        "review",
        {"outcome": "verified", "next_review_at": (utc_now() + timedelta(days=90)).isoformat()},
        asset=asset,
        user=user,
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    "asset,user,allowed",
    [
        (KA_COMPANY_L2, USER_BOSS, True),
        (KA_COMPANY_L2, USER_DIRECTOR, True),
        (KA_COMPANY_L2, USER_CONSULTANT, False),
        (KA_COMPANY_L2, USER_ADMIN_ONLY, False),
        (KA_PROJECT_ALPHA, USER_PROJECT_MANAGER, True),
        (KA_PROJECT_ALPHA, USER_BOSS, False),
        (KA_PERSONAL, USER_CONSULTANT, True),
        (KA_PERSONAL, USER_DIRECTOR, False),
    ],
)
async def test_scope_governance_matrix(client, asset, user, allowed):
    response = await client.patch(
        f"/api/v1/knowledge/{asset}/trust/policy",
        headers=headers(user),
        json={
            "expected_updated_at": utc_now().isoformat(),
            "reason": "安排复核",
            "maintainer_user_id": str(user),
            "review_due_at": (utc_now() + timedelta(days=10)).isoformat(),
        },
    )
    assert response.status_code == (409 if allowed else 404), response.text


async def test_policy_does_not_grant_permission_and_invalid_dates_rejected(client):
    response = await command(
        client,
        "policy",
        {
            "maintainer_user_id": str(USER_CONSULTANT),
            "review_due_at": (utc_now() + timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 422
    response = await command(
        client,
        "policy",
        {
            "maintainer_user_id": str(USER_BOSS),
            "review_due_at": (utc_now() - timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 422


async def test_review_stale_submission_and_metadata_invalidation(client):
    first = await policy(client)
    verified = await verify(client)
    assert verified["freshness"] == "verified"
    stale = await client.post(
        f"/api/v1/knowledge/{KA_COMPANY_L2}/trust/review",
        headers=headers(USER_BOSS),
        json={
            "expected_updated_at": first["updated_at"],
            "reason": "旧页面",
            "outcome": "needs_update",
        },
    )
    assert stale.status_code == 409
    changed = await client.patch(
        f"/api/v1/knowledge/{KA_COMPANY_L2}/metadata",
        headers=headers(USER_BOSS),
        json={
            "expected_updated_at": verified["updated_at"],
            "reason": "更正",
            "title": "修订后的标题",
        },
    )
    assert changed.status_code == 200
    assert (await state(client))["freshness"] == "changed"


@pytest.mark.parametrize("change", ["maintainer", "date", "both"])
async def test_maintenance_changes_preserve_current_verification(client, db_session, change):
    await policy(client)
    current = await verify(client)
    before = await db_session.get(KnowledgeAsset, KA_COMPANY_L2)
    await db_session.refresh(before)
    reviewer = before.verified_by_user_id
    response = await command(
        client,
        "policy",
        {
            "maintainer_user_id": str(
                USER_DIRECTOR if change in {"maintainer", "both"} else USER_BOSS
            ),
            "review_due_at": (utc_now() + timedelta(days=120)).isoformat()
            if change in {"date", "both"}
            else current["review_due_at"],
        },
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["freshness"] == "verified"
    assert stamp(datetime.fromisoformat(updated["verified_at"].replace("Z", "+00:00"))) == stamp(
        datetime.fromisoformat(current["verified_at"].replace("Z", "+00:00"))
    )
    assert updated["updated_at"] != current["updated_at"]
    await db_session.refresh(before)
    assert before.verified_by_user_id == reviewer
    queue = await client.get("/api/v1/knowledge-maintenance", headers=headers(USER_BOSS))
    assert str(KA_COMPANY_L2) not in {item["asset_id"] for item in queue.json()["items"]}
    # Old metadata and governance forms must still fail, despite preserved freshness.
    stale = await client.patch(
        f"/api/v1/knowledge/{KA_COMPANY_L2}/metadata",
        headers=headers(USER_BOSS),
        json={
            "expected_updated_at": current["updated_at"],
            "reason": "旧页面",
            "title": "覆盖",
        },
    )
    assert stale.status_code == 409
    stale = await client.patch(
        f"/api/v1/knowledge/{KA_COMPANY_L2}/trust/policy",
        headers=headers(USER_BOSS),
        json={
            "expected_updated_at": current["updated_at"],
            "reason": "旧安排",
            "maintainer_user_id": str(USER_BOSS),
            "review_due_at": current["review_due_at"],
        },
    )
    assert stale.status_code == 409
    # A later actual content/metadata change still invalidates verification.
    changed = await client.patch(
        f"/api/v1/knowledge/{KA_COMPANY_L2}/metadata",
        headers=headers(USER_BOSS),
        json={
            "expected_updated_at": updated["updated_at"],
            "reason": "修正标题",
            "title": "真正修改内容",
        },
    )
    assert changed.status_code == 200, changed.text
    assert (await state(client))["freshness"] == "changed"


@pytest.mark.parametrize("prior_state", ["unreviewed", "changed", "needs_update"])
async def test_maintenance_changes_do_not_revalidate_invalid_content(client, prior_state):
    await policy(client)
    if prior_state != "unreviewed":
        current = await verify(client)
        if prior_state == "changed":
            changed = await client.patch(
                f"/api/v1/knowledge/{KA_COMPANY_L2}/metadata",
                headers=headers(USER_BOSS),
                json={
                    "expected_updated_at": current["updated_at"],
                    "reason": "修正",
                    "title": "未复核的修改",
                },
            )
            assert changed.status_code == 200
        else:
            assert (await command(client, "review", {"outcome": "needs_update"})).status_code == 200
    result = await policy(client)
    assert result["freshness"] == prior_state


async def test_due_notification_deduplicates_without_archiving(client, db_session):
    await policy(client)
    asset = await db_session.get(KnowledgeAsset, KA_COMPANY_L2)
    asset.review_due_at = utc_now() - timedelta(days=1)
    await db_session.commit()
    await scan_due_reviews(db_session)
    await scan_due_reviews(db_session)
    rows = (
        await db_session.scalars(
            select(BusinessNotification).where(
                BusinessNotification.event_type == "knowledge.due",
                BusinessNotification.recipient_user_id == USER_BOSS,
            )
        )
    ).all()
    assert len(rows) == 1
    await db_session.refresh(asset)
    assert asset.asset_status == "active"
    assert (await state(client))["freshness"] == "due"


async def test_correction_full_loop_and_private_reports(client):
    await policy(client)
    reported = await command(client, "corrections", {}, user=USER_CONSULTANT)
    assert reported.status_code == 200, reported.text
    ticket = reported.json()["corrections"][0]
    # Another ordinary reader cannot read somebody else's submitted content.
    assert (await state(client, user=USER_PROJECT_MANAGER))["corrections"] == []
    url = f"/api/v1/knowledge/{KA_COMPANY_L2}/trust/corrections/{ticket['id']}"
    body = {"expected_updated_at": ticket["updated_at"], "reason": "已修正", "action": "resolve"}
    assert (await client.post(url, headers=headers(USER_BOSS), json=body)).status_code == 409
    # Changing only maintenance dates is not evidence of correction.
    await policy(client)
    assert (await client.post(url, headers=headers(USER_BOSS), json=body)).status_code == 409
    current = await state(client)
    changed = await client.patch(
        f"/api/v1/knowledge/{KA_COMPANY_L2}/metadata",
        headers=headers(USER_BOSS),
        json={
            "expected_updated_at": current["updated_at"],
            "reason": "纠正",
            "title": "正确的资料标题",
        },
    )
    assert changed.status_code == 200
    resolved = await client.post(url, headers=headers(USER_BOSS), json=body)
    assert resolved.status_code == 200, resolved.text
    ticket = resolved.json()["corrections"][0]
    assert ticket["status"] == "resolved"
    await verify(client)
    body = {"expected_updated_at": ticket["updated_at"], "reason": "已经解决", "action": "verify"}
    assert (await client.post(url, headers=headers(USER_BOSS), json=body)).status_code == 409
    response = await client.post(url, headers=headers(USER_CONSULTANT), json=body)
    assert response.status_code == 200, response.text
    assert response.json()["corrections"][0]["status"] == "verified"
    assert (await client.post(url, headers=headers(USER_CONSULTANT), json=body)).status_code == 409


async def test_replacement_requires_verified_same_scope_target_and_archives(client, db_session):
    target_id = uuid.uuid4()
    target = KnowledgeAsset(
        id=target_id,
        title="新版",
        scope="company",
        zone="asset",
        asset_type="methodology",
        owner_user_id=USER_BOSS,
        confidentiality_level="L2",
        ai_access_level="A1",
        asset_status="active",
    )
    db_session.add(target)
    version = KnowledgeAssetVersion(
        asset_id=target_id, version_no="V2", version_status="active", created_by=USER_BOSS
    )
    db_session.add(version)
    await db_session.flush()
    target.current_version_id = version.id
    await db_session.commit()
    await policy(client, asset=target_id)
    target_state = await verify(client, asset=target_id)
    options = await client.get(
        f"/api/v1/knowledge/{KA_COMPANY_L2}/trust/replacements?keyword=新版",
        headers=headers(USER_BOSS),
    )
    assert options.status_code == 200, options.text
    assert options.json() == [{"asset_id": str(target_id), "title": "新版"}]
    response = await command(
        client,
        "replacement",
        {
            "replacement_asset_id": str(target_id),
            "expected_replacement_updated_at": target_state["updated_at"],
            "confirm_archive": True,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["replacement_asset_id"] == str(target_id)
    assert response.json()["freshness"] == "archived"
    ordinary = await client.get(
        f"/api/v1/knowledge/{KA_COMPANY_L2}", headers=headers(USER_CONSULTANT)
    )
    assert ordinary.status_code == 404
    response = await client.post(
        f"/api/v1/knowledge/{KA_COMPANY_L2}/lifecycle/reenable-confirm",
        headers=headers(USER_BOSS),
        json={"target_status": "active", "reason": "恢复"},
    )
    assert response.status_code == 409
    response = await command(client, "replacement", {"replacement_asset_id": None})
    assert response.status_code == 200
    assert response.json()["freshness"] == "archived"


async def test_maintenance_list_is_scoped_and_admin_cannot_read(client):
    response = await client.get("/api/v1/knowledge-maintenance", headers=headers(USER_CONSULTANT))
    assert response.status_code == 200, response.text
    ids = {row["asset_id"] for row in response.json()["items"]}
    assert str(KA_COMPANY_L2) not in ids and str(KA_PROJECT_ALPHA) not in ids
    assert str(KA_PERSONAL) in ids
    response = await client.get("/api/v1/knowledge-maintenance", headers=headers(USER_ADMIN_ONLY))
    assert response.status_code == 403


async def test_open_correction_blocks_review_and_repeat_submission(client):
    await policy(client)
    assert (await command(client, "corrections", {}, user=USER_CONSULTANT)).status_code == 200
    assert (await command(client, "corrections", {}, user=USER_CONSULTANT)).status_code == 409
    response = await command(
        client,
        "review",
        {"outcome": "verified", "next_review_at": (utc_now() + timedelta(days=10)).isoformat()},
    )
    assert response.status_code == 409


async def test_modified_resolution_requires_reopen_and_another_fix(client):
    await policy(client)
    reported = await command(client, "corrections", {}, user=USER_CONSULTANT)
    ticket = reported.json()["corrections"][0]
    current = await state(client)
    url = f"/api/v1/knowledge/{KA_COMPANY_L2}/metadata"
    assert (
        await client.patch(
            url,
            headers=headers(USER_BOSS),
            json={
                "expected_updated_at": current["updated_at"],
                "reason": "修订",
                "title": "第一版修正",
            },
        )
    ).status_code == 200
    ticket_url = f"/api/v1/knowledge/{KA_COMPANY_L2}/trust/corrections/{ticket['id']}"
    response = await client.post(
        ticket_url,
        headers=headers(USER_BOSS),
        json={
            "expected_updated_at": ticket["updated_at"],
            "reason": "已修改",
            "action": "resolve",
        },
    )
    assert response.status_code == 200
    ticket = response.json()["corrections"][0]
    current = await verify(client)
    assert (
        await client.patch(
            url,
            headers=headers(USER_BOSS),
            json={
                "expected_updated_at": current["updated_at"],
                "reason": "再次修订",
                "title": "其它修改",
            },
        )
    ).status_code == 200
    response = await client.post(
        ticket_url,
        headers=headers(USER_CONSULTANT),
        json={
            "expected_updated_at": ticket["updated_at"],
            "reason": "确认",
            "action": "verify",
        },
    )
    assert response.status_code == 409
    response = await client.post(
        ticket_url,
        headers=headers(USER_CONSULTANT),
        json={
            "expected_updated_at": ticket["updated_at"],
            "reason": "仍有问题",
            "action": "reopen",
        },
    )
    assert response.status_code == 200
    ticket = response.json()["corrections"][0]
    assert ticket["status"] == "open"
    response = await client.post(
        ticket_url,
        headers=headers(USER_BOSS),
        json={
            "expected_updated_at": ticket["updated_at"],
            "reason": "直接重试",
            "action": "resolve",
        },
    )
    assert response.status_code == 409

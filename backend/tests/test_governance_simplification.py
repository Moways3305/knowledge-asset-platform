"""Optional governance, shared facts, and explicit per-asset delegation boundaries."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from test_knowledge_review import command, headers, state
from test_maintenance_agent import configure

from app.db.utils import as_utc, utc_now
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.lifecycle import AlertRule, AssetLifecycleEvent
from app.models.maintenance_agent import MaintenanceIssue, MaintenancePolicy
from app.models.preview import PreviewCredential
from app.schemas.maintenance_agent import ScanSettings
from app.seed.dev_seed import (
    KA_COMPANY_L2,
    KA_COMPANY_L4,
    KA_COMPANY_L5,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
)
from app.services.maintenance_access import actor_context
from app.services.maintenance_rules import deterministic
from app.services.permission import AccessChannel, AccessLayer, decide


@pytest.mark.parametrize("days", [None, 30, 365])
async def test_review_without_assignment_and_optional_schedule(client, days):
    response = await command(client, "policy", {"review_interval_days": days})
    assert response.status_code == 200, response.text
    assert response.json()["maintainer_user_id"] is None
    result = await command(client, "review", {"outcome": "verified"})
    assert result.status_code == 200, result.text
    assert result.json()["freshness"] == "verified"
    if days:
        from datetime import datetime

        due = datetime.fromisoformat(result.json()["review_due_at"].replace("Z", "+00:00"))
        assert abs((due - utc_now()).total_seconds() - days * 86400) < 10
    else:
        assert result.json()["review_due_at"] is None
    listing = await client.get("/api/v1/knowledge-maintenance", headers=headers(USER_BOSS))
    assert str(KA_COMPANY_L2) not in {row["asset_id"] for row in listing.json()["items"]}


def test_missing_optional_date_tags_owner_do_not_create_mandatory_tasks():
    now = utc_now()
    snapshot = {
        "facts": dict(
            id="asset",
            title="资料",
            has_summary=True,
            directory="general",
            valid_maintainer=True,
            tags=[],
            parse_status="completed",
            index_status="indexed",
            review_due=None,
            old_correction=False,
            status="active",
            updated_at=now,
            file_hash="",
        ),
        "candidates": [],
    }
    assert deterministic(snapshot, ScanSettings(), now) == []
    findings = deterministic(snapshot, ScanSettings(required_tags=["政策"]), now)
    assert [f["rule"] for f in findings] == ["missing_tags"]


@pytest.mark.parametrize(
    "action,status,user",
    [
        ("reject", "rejected", USER_BOSS),
        ("duplicate", "duplicate", USER_BOSS),
        ("withdraw", "withdrawn", USER_CONSULTANT),
    ],
)
async def test_feedback_can_close_without_fake_content_edits_and_reopen(
    client, action, status, user
):
    initial = await state(client)
    reported = await command(client, "corrections", {}, user=USER_CONSULTANT)
    ticket = reported.json()["corrections"][0]
    route = f"/api/v1/knowledge/{KA_COMPANY_L2}/trust/corrections/{ticket['id']}"
    done = await client.post(
        route,
        headers=headers(user),
        json={
            "expected_updated_at": ticket["updated_at"],
            "reason": "已核对反馈依据",
            "action": action,
        },
    )
    assert done.status_code == 200, done.text
    ticket = done.json()["corrections"][0]
    assert ticket["status"] == status
    assert (await state(client))["updated_at"] == initial["updated_at"]
    reopened = await client.post(
        route,
        headers=headers(USER_CONSULTANT),
        json={
            "expected_updated_at": ticket["updated_at"],
            "reason": "补充新依据",
            "action": "reopen",
        },
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["corrections"][0]["status"] == "open"


@pytest.mark.parametrize("actor,action", [(USER_CONSULTANT, "verify"), (USER_BOSS, "close")])
async def test_fixed_feedback_does_not_require_an_extra_review(client, actor, action):
    response = await command(client, "corrections", {}, user=USER_CONSULTANT)
    ticket = response.json()["corrections"][0]
    route = f"/api/v1/knowledge/{KA_COMPANY_L2}/trust/corrections/{ticket['id']}"
    current = await state(client)
    edited = await client.patch(
        f"/api/v1/knowledge/{KA_COMPANY_L2}/metadata",
        headers=headers(USER_BOSS),
        json={
            "expected_updated_at": current["updated_at"],
            "reason": "修正标题",
            "title": "已修正的资料",
        },
    )
    assert edited.status_code == 200, edited.text
    response = await client.post(
        route,
        headers=headers(USER_BOSS),
        json={"expected_updated_at": ticket["updated_at"], "reason": "已修正", "action": "resolve"},
    )
    assert response.status_code == 200, response.text
    ticket = response.json()["corrections"][0]
    assert response.json()["verified_at"] is None
    result = await client.post(
        route,
        headers=headers(actor),
        json={
            "expected_updated_at": ticket["updated_at"],
            "reason": "确认已解决",
            "action": action,
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["corrections"][0]["status"] == "verified"


async def test_delegation_requires_explicit_grant_and_revokes_preview(client, db_session):
    assigned = {"maintainer_user_id": str(USER_CONSULTANT)}
    assert (await command(client, "policy", assigned)).status_code == 422
    granted = await command(client, "policy", {**assigned, "maintenance_delegated": True})
    assert granted.status_code == 200, granted.text
    delegate = await state(client, user=USER_CONSULTANT)
    assert delegate["can_manage"] and not delegate["can_assign"]
    asset = await db_session.get(KnowledgeAsset, KA_COMPANY_L2)
    caller = await actor_context(db_session, USER_CONSULTANT, "consultant")
    assert decide(caller, asset, AccessLayer.original).allowed
    assert not decide(caller, asset, AccessLayer.original, channel=AccessChannel.agent).allowed
    edited = await client.patch(
        f"/api/v1/knowledge/{KA_COMPANY_L2}/metadata",
        headers=headers(USER_CONSULTANT),
        json={
            "expected_updated_at": delegate["updated_at"],
            "reason": "补充标题",
            "title": "维护人修正的标题",
        },
    )
    assert edited.status_code == 200, edited.text
    current = await state(client, user=USER_CONSULTANT)
    classified = await client.patch(
        f"/api/v1/knowledge/{KA_COMPANY_L2}/metadata",
        headers=headers(USER_CONSULTANT),
        json={
            "expected_updated_at": current["updated_at"],
            "reason": "改密级",
            "confidentiality_level": "L3",
        },
    )
    assert classified.status_code == 403
    reassigned = await command(
        client, "policy", {"maintainer_user_id": str(USER_DIRECTOR)}, user=USER_CONSULTANT
    )
    assert reassigned.status_code == 403
    archived = await client.post(
        f"/api/v1/knowledge/{KA_COMPANY_L2}/lifecycle/archive-confirm",
        headers=headers(USER_CONSULTANT),
        json={"reason": "归档"},
    )
    assert archived.status_code == 403
    replaced = await command(
        client, "replacement", {"replacement_asset_id": None}, user=USER_CONSULTANT
    )
    assert replaced.status_code == 403
    cred = PreviewCredential(
        target_asset_id=KA_COMPANY_L2,
        requester_user_id=USER_CONSULTANT,
        requester_company_role="consultant",
        preview_type="original",
        token_hash="test-hash",
        credential_fingerprint="test",
        preview_entry_url="/preview/test",
        expires_at=utc_now() + timedelta(hours=1),
    )
    db_session.add(cred)
    await db_session.commit()
    assert (await command(client, "policy", {})).status_code == 200
    await db_session.refresh(cred)
    assert cred.credential_status == "revoked"
    assert not (await state(client, user=USER_CONSULTANT))["can_manage"]
    await db_session.refresh(asset)
    assert not decide(caller, asset, AccessLayer.original).allowed


async def issue_fixture(client, db_session, rules):
    await configure(client)
    policy = await db_session.scalar(select(MaintenancePolicy))
    asset = await db_session.get(KnowledgeAsset, KA_COMPANY_L2)
    rows = [
        MaintenanceIssue(
            policy_id=policy.id,
            asset_id=asset.id,
            version_id=asset.current_version_id,
            rule=rule,
            category="integrity" if rule.startswith("missing") else "quality",
            fingerprint=rule,
        )
        for rule in rules
    ]
    db_session.add_all(rows)
    await db_session.commit()
    return rows


async def test_delegation_does_not_extend_to_other_assets_l5_or_version_publication(
    client, db_session
):
    granted = await command(
        client,
        "policy",
        {"maintainer_user_id": str(USER_CONSULTANT), "maintenance_delegated": True},
    )
    assert granted.status_code == 200
    caller = await actor_context(db_session, USER_CONSULTANT, "consultant")
    other = await db_session.get(KnowledgeAsset, KA_COMPANY_L4)
    assert not decide(caller, other, AccessLayer.original).allowed
    result = await command(
        client,
        "policy",
        {"maintainer_user_id": str(USER_CONSULTANT), "maintenance_delegated": True},
        asset=KA_COMPANY_L5,
    )
    assert result.status_code == 422
    history = await client.get(
        f"/api/v1/knowledge/{KA_COMPANY_L2}/versions", headers=headers(USER_CONSULTANT)
    )
    assert history.status_code == 200, history.text
    assert not history.json()["can_update"]
    assert not history.json()["updates"]


async def test_suggestions_are_separate_and_retired_issues_hidden_then_reconciled(
    client, db_session
):
    rows = await issue_fixture(
        client, db_session, ["missing_review_date", "missing_summary", "summary_mismatch"]
    )
    route = "/api/v1/maintenance-agent/issues"
    response = await client.get(route + "?priority=actionable", headers=headers(USER_BOSS))
    assert response.status_code == 200, response.text
    assert response.json()["counts"] == {"actionable": 1, "suggestion": 1}
    assert [r["rule"] for r in response.json()["items"]] == ["summary_mismatch"]
    listing = await client.get("/api/v1/knowledge-maintenance", headers=headers(USER_BOSS))
    item = next(r for r in listing.json()["items"] if r["asset_id"] == str(KA_COMPANY_L2))
    assert item["agent_issue_count"] == 1
    current = await state(client)
    result = await client.patch(
        f"/api/v1/knowledge/{KA_COMPANY_L2}/metadata",
        headers=headers(USER_BOSS),
        json={
            "expected_updated_at": current["updated_at"],
            "reason": "补齐摘要",
            "summary": "资料摘要已补齐。",
        },
    )
    assert result.status_code == 200, result.text
    for row in rows:
        await db_session.refresh(row)
    assert [r.status for r in rows] == ["not_applicable", "resolved", "open"]
    # AI findings need evidence-based rechecking; metadata writes cannot clear them.
    foreign = await client.get(route + f"?asset_id={uuid.uuid4()}", headers=headers(USER_BOSS))
    assert foreign.json()["total"] == 0


async def test_company_replacement_uses_real_relation_and_single_content_confirmation(
    client, db_session
):
    await configure(client)
    policy = await db_session.scalar(select(MaintenancePolicy))
    target = KnowledgeAsset(
        title="已核对的新版",
        scope="company",
        zone="asset",
        asset_type="methodology",
        owner_user_id=USER_BOSS,
        confidentiality_level="L2",
        ai_access_level="A1",
        asset_status="active",
    )
    db_session.add(target)
    await db_session.flush()
    version = KnowledgeAssetVersion(
        asset_id=target.id, version_no="V2", version_status="active", created_by=USER_BOSS
    )
    db_session.add(version)
    await db_session.flush()
    target.current_version_id = version.id
    target.review_due_at = utc_now() - timedelta(days=1)
    overdue = MaintenanceIssue(
        policy_id=policy.id,
        asset_id=target.id,
        version_id=version.id,
        rule="review_overdue",
        category="maintenance",
        fingerprint="old-due-date",
    )
    db_session.add(overdue)
    await db_session.commit()
    old, new = await state(client), await state(client, target.id)
    response = await client.post(
        "/api/v1/company-governance/batch",
        headers=headers(USER_BOSS),
        json={
            "items": [
                {
                    "asset_id": str(KA_COMPANY_L2),
                    "expected_status": "active",
                    "expected_updated_at": old["updated_at"],
                }
            ],
            "action": "archive",
            "reason_code": "superseded",
            "reason": "采用新版内容",
            "replacement_asset_id": str(target.id),
            "expected_replacement_updated_at": new["updated_at"],
            "confirm_replacement": True,
        },
    )
    assert response.status_code == 200 and response.json()["items"][0]["success"], response.text
    source = await db_session.get(KnowledgeAsset, KA_COMPANY_L2)
    await db_session.refresh(source)
    await db_session.refresh(target)
    assert source.replacement_asset_id == target.id and source.asset_status == "archived"
    assert target.verified_at is not None and target.review_due_at is None
    await db_session.refresh(overdue)
    assert overdue.status == "resolved"


async def test_disabled_archive_rule_really_stops_scan(client, db_session):
    from app.services.alert import ensure_default_rules
    from app.services.jobs.lifecycle_scan import scan_archive_candidates

    await ensure_default_rules(db_session)
    rule = await db_session.scalar(
        select(AlertRule).where(AlertRule.rule_name == "长期未调用归档预警")
    )
    rule.enabled = False
    asset = await db_session.get(KnowledgeAsset, KA_COMPANY_L2)
    asset.created_at = utc_now() - timedelta(days=1000)
    asset.last_called_at = None
    await db_session.commit()
    result = await scan_archive_candidates(db_session)
    assert result == {"warnings": 0, "candidates": 0, "scanned": 0}
    assert not await db_session.scalar(
        select(AssetLifecycleEvent.id).where(AssetLifecycleEvent.asset_id == asset.id)
    )


def test_shared_utc_normalization():
    now = utc_now()
    assert as_utc(now.replace(tzinfo=None)) == now
    assert as_utc(None) is None

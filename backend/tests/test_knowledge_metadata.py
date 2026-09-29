"""Metadata editing scope matrix and security regression tests (existing tests retained)."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db.utils import utc_now
from app.models.audit import AuditEvent
from app.models.knowledge import KnowledgeAsset
from app.models.original_access import AccessGrant
from app.models.preview import PreviewCredential
from app.seed.dev_seed import (
    KA_COMPANY_L2,
    KA_PERSONAL,
    KA_PROJECT_ALPHA,
    PROJECT_BETA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
    USER_PROJECT_MANAGER,
)


def headers(user):
    return {"X-Dev-User-Id": str(user)}


async def edit(client, asset, user, **changes):
    detail = await client.get(f"/api/v1/knowledge/{asset}", headers=headers(user))
    timestamp = detail.json().get("updated_at") or utc_now().isoformat()
    return await client.patch(
        f"/api/v1/knowledge/{asset}/metadata",
        headers=headers(user),
        json={"expected_updated_at": timestamp, "reason": "纠正录入错误", **changes},
    )


@pytest.mark.parametrize(
    "asset,user,allowed",
    [
        (KA_COMPANY_L2, USER_BOSS, True),
        (KA_COMPANY_L2, USER_DIRECTOR, True),
        (KA_COMPANY_L2, USER_CONSULTANT, False),
        (KA_COMPANY_L2, USER_PROJECT_MANAGER, False),
        (KA_COMPANY_L2, USER_ADMIN_ONLY, False),
        (KA_PROJECT_ALPHA, USER_PROJECT_MANAGER, True),
        (KA_PROJECT_ALPHA, USER_CONSULTANT, False),
        (KA_PROJECT_ALPHA, USER_BOSS, False),
        (KA_PROJECT_ALPHA, USER_DIRECTOR, False),
        (KA_PERSONAL, USER_CONSULTANT, True),
        (KA_PERSONAL, USER_BOSS, False),
    ],
)
async def test_scope_matrix(client, asset, user, allowed):
    response = await edit(client, asset, user, title="更正后的资料标题")
    assert response.status_code == (200 if allowed else 404), response.text


async def test_cannot_manage_other_project(client, db_session):
    asset = await db_session.get(KnowledgeAsset, KA_PROJECT_ALPHA)
    asset.project_id = PROJECT_BETA
    await db_session.commit()
    response = await edit(client, asset.id, USER_PROJECT_MANAGER, title="越权修改")
    assert response.status_code == 404


async def test_stale_edit_conflict(client):
    detail = (
        await client.get(f"/api/v1/knowledge/{KA_COMPANY_L2}", headers=headers(USER_BOSS))
    ).json()
    body = {"expected_updated_at": detail["updated_at"], "reason": "更正", "title": "第一次修改"}
    url = f"/api/v1/knowledge/{KA_COMPANY_L2}/metadata"
    assert (await client.patch(url, headers=headers(USER_BOSS), json=body)).status_code == 200
    body["title"] = "旧页面覆盖"
    assert (await client.patch(url, headers=headers(USER_BOSS), json=body)).status_code == 409


@pytest.mark.parametrize(
    "changes",
    [
        {"title": None},
        {"title": "   "},
        {"tags": [""]},
        {"owner_user_id": str(USER_BOSS)},
        {"scope": "company"},
        {"ai_access_level": "A1"},
        {"summary": ""},
        {},
    ],
)
async def test_reject_invalid_or_uncontrolled_fields(client, changes):
    response = await edit(client, KA_COMPANY_L2, USER_BOSS, **changes)
    assert response.status_code == 422, response.text


async def test_downgrade_requires_confirmation(client):
    response = await edit(client, KA_COMPANY_L2, USER_BOSS, confidentiality_level="L1")
    assert response.status_code == 422
    response = await edit(
        client, KA_COMPANY_L2, USER_BOSS, confidentiality_level="L1", confirm_downgrade=True
    )
    assert response.status_code == 200


async def test_elevation_revokes_capabilities_and_preserves_ai(client, db_session):
    asset = await db_session.get(KnowledgeAsset, KA_COMPANY_L2)
    previous_ai = asset.ai_access_level
    grant = AccessGrant(
        asset_id=asset.id,
        grantee_user_id=USER_CONSULTANT,
        granted_by_user_id=USER_BOSS,
        status="active",
    )
    credential = PreviewCredential(
        target_asset_id=asset.id,
        requester_user_id=USER_CONSULTANT,
        preview_type="pdf",
        token_hash="test-only",
        credential_fingerprint="test-only",
        preview_entry_url="/test",
        expires_at=utc_now() + timedelta(hours=1),
    )
    db_session.add_all([grant, credential])
    await db_session.commit()
    response = await edit(client, asset.id, USER_BOSS, confidentiality_level="L5")
    assert response.status_code == 200, response.text
    await db_session.refresh(grant)
    await db_session.refresh(credential)
    await db_session.refresh(asset)
    assert grant.status == "revoked"
    assert credential.credential_status == "revoked"
    assert asset.ai_access_level == previous_ai
    assert (
        await client.get(f"/api/v1/knowledge/{asset.id}", headers=headers(USER_CONSULTANT))
    ).status_code == 404


async def test_summary_redaction_audit_and_file_identity(client, db_session):
    asset = await db_session.get(KnowledgeAsset, KA_COMPANY_L2)
    version_id = asset.current_version_id
    response = await edit(
        client,
        asset.id,
        USER_BOSS,
        summary="联系方式 13812345678，修正后的摘要",
        tags=["新标签", "新标签"],
    )
    assert response.status_code == 200, response.text
    detail = (
        await client.get(f"/api/v1/knowledge/{asset.id}", headers=headers(USER_CONSULTANT))
    ).json()
    assert "13812345678" not in str(detail["summary"])
    assert detail["tags"] == ["新标签"]
    await db_session.refresh(asset)
    assert asset.current_version_id == version_id
    events = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.target_id == asset.id)))
        .scalars()
        .all()
    )
    assert events
    assert "13812345678" not in str([event.__dict__ for event in events])


async def test_directory_scope_validation(client):
    response = await edit(client, KA_COMPANY_L2, USER_BOSS, directory_key="project.deliverables")
    assert response.status_code == 422
    response = await edit(client, KA_COMPANY_L2, USER_BOSS, directory_key="company.methodology")
    assert response.status_code == 200, response.text


async def test_overlapping_tags_do_not_violate_unique_constraint(client):
    assert (
        await edit(client, KA_COMPANY_L2, USER_BOSS, tags=["保留", "旧标签"])
    ).status_code == 200
    assert (
        await edit(client, KA_COMPANY_L2, USER_BOSS, tags=["保留", "新标签"])
    ).status_code == 200


async def test_personal_project_copy_lock(client, db_session):
    original = await db_session.get(KnowledgeAsset, KA_PERSONAL)
    copy = KnowledgeAsset(
        id=uuid.uuid4(),
        title="项目使用中的副本",
        scope="project",
        zone="material",
        asset_type="unclassified",
        owner_user_id=USER_CONSULTANT,
        source_asset_id=original.id,
        project_id=PROJECT_BETA,
        asset_status="active",
    )
    db_session.add(copy)
    await db_session.commit()
    response = await edit(client, original.id, USER_CONSULTANT, title="不允许更改")
    assert response.status_code == 409


async def test_archived_not_editable(client, db_session):
    asset = await db_session.get(KnowledgeAsset, KA_COMPANY_L2)
    asset.asset_status = "archived"
    await db_session.commit()
    assert (await edit(client, asset.id, USER_BOSS, title="不能绕过归档")).status_code == 404

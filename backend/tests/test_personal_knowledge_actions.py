"""个人知识写动作测试。

覆盖：本人资产确认（含幂等）、非 owner / 纯 admin 404、提交到项目（成员 / 非成员 /
治理角色）、Idempotency-Key 与无 key 的 pending 去重、内部分享 / 客户验证候选证据登记、
审核任务创建、审计安全无泄露。
"""

from __future__ import annotations

import uuid

import pytest_asyncio
from sqlalchemy import func, select

from app.models.audit import AuditEvent
from app.models.identity import Project
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.naming import NamingRuleRevision
from app.models.review import PersonalKnowledgeSubmission, ReviewTask
from app.seed.dev_seed import (
    PROJECT_ALPHA,
    PROJECT_BETA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_PROJECT_MANAGER,
)
from app.services.directories import default_directory_config

_LEAK_TOKENS = [
    "storage_ref",
    "source_file_ref",
    "weknora",
    "access_token",
    "oauth_state",
    "download_url",
    "token_hash",
    "app_secret",
    "content_text",
]
PROJECT_CATEGORY_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")


@pytest_asyncio.fixture(autouse=True)
async def governed_publication_policy(sessionmaker_fixture):
    async with sessionmaker_fixture() as session:
        project = await session.get(Project, PROJECT_ALPHA)
        project.project_code = "ALPHA"
        project.project_code_active = True
        session.add(
            NamingRuleRevision(
                version=10,
                status="published",
                base_published_version=9,
                config={
                    "schema_version": 2,
                    "enforced": True,
                    "project_codes": [],
                    "categories": [
                        {
                            "id": str(PROJECT_CATEGORY_ID),
                            "scope": "project",
                            "primary": "项目资料",
                            "secondary": "交付成果",
                            "prefix": "交付",
                            "asset_type": "deliverable",
                            "default_confidentiality": "L2",
                            "enabled": True,
                            "sort_order": 10,
                            "suggested_directory_key": "project.deliverables",
                        }
                    ],
                    "directories": default_directory_config(),
                },
            )
        )
        await session.commit()


def _project_publication_body(project_id=PROJECT_ALPHA):
    return {
        "target_project_id": str(project_id),
        "confidentiality_level": "L2",
        "naming": {
            "category_id": str(PROJECT_CATEGORY_ID),
            "subject": "个人知识草稿",
            "formed_on": "2026-08-17",
            "version": "V1",
            "directory_key": "project.deliverables",
        },
    }


def _hdr(user_id, **extra):
    return {"X-Dev-User-Id": str(user_id), **extra}


def _assert_no_leak(text: str):
    low = text.lower()
    for t in _LEAK_TOKENS:
        assert t.lower() not in low, f"不应泄露 {t}"


async def _mk_personal(db_session, *, owner, zone="material", status="active") -> uuid.UUID:
    """插入一条个人知识资产，返回 id。client 与 db_session 共用同一内存库。"""
    aid = uuid.uuid4()
    asset = KnowledgeAsset(
        id=aid,
        title="个人知识草稿",
        scope="personal",
        zone=zone,
        asset_type="methodology",
        owner_user_id=owner,
        asset_status=status,
        confidentiality_level="L2",
    )
    db_session.add(asset)
    await db_session.flush()
    version = KnowledgeAssetVersion(
        asset_id=aid,
        version_no="V1",
        version_status="active",
        created_by=owner,
        index_status="indexed",
        directory_key="personal.learning_notes",
    )
    db_session.add(version)
    await db_session.flush()
    asset.current_version_id = version.id
    await db_session.commit()
    return aid


def _confirm(aid):
    return f"/api/v1/my/knowledge/{aid}/confirm-asset"


def _submit(aid):
    return f"/api/v1/my/knowledge/{aid}/submit-to-project"


def _evidence(aid):
    return f"/api/v1/my/knowledge/{aid}/validation-evidence"


# ---------------- 本人资产确认 ----------------
async def test_owner_confirm_material_to_asset(client, db_session):
    aid = await _mk_personal(db_session, owner=USER_CONSULTANT, zone="material")
    r = await client.post(
        _confirm(aid), headers=_hdr(USER_CONSULTANT, **{"X-Trace-Id": "trc-personal-confirm"})
    )
    assert r.status_code == 200, r.text
    assert r.json()["zone"] == "asset" and r.json()["status"] == "confirmed"
    rows = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "review.personal_asset_confirmed")
            )
        )
        .scalars()
        .all()
    )
    assert rows and (rows[-1].after_snapshot or {}).get("zone") == "asset"


async def test_confirm_asset_idempotent(client, db_session):
    aid = await _mk_personal(db_session, owner=USER_CONSULTANT, zone="material")
    r1 = await client.post(_confirm(aid), headers=_hdr(USER_CONSULTANT))
    assert r1.status_code == 200 and r1.json()["status"] == "confirmed"
    r2 = await client.post(_confirm(aid), headers=_hdr(USER_CONSULTANT))
    assert r2.status_code == 200 and r2.json()["status"] == "already_asset"
    assert r2.json()["zone"] == "asset"


async def test_non_owner_confirm_404(client, db_session):
    aid = await _mk_personal(db_session, owner=USER_CONSULTANT, zone="material")
    r = await client.post(_confirm(aid), headers=_hdr(USER_PROJECT_MANAGER))
    assert r.status_code == 404
    assert r.json()["detail"]["denied_reason"] == "personal_asset_not_owned"


async def test_admin_cannot_operate_personal(client, db_session):
    aid = await _mk_personal(db_session, owner=USER_CONSULTANT, zone="material")
    r = await client.post(_confirm(aid), headers=_hdr(USER_ADMIN_ONLY))
    assert r.status_code == 404
    assert r.json()["detail"]["denied_reason"] == "personal_asset_not_owned"


# ---------------- 提交到项目 ----------------
async def test_submit_to_member_project_creates_submission_and_review(client, db_session):
    aid = await _mk_personal(db_session, owner=USER_CONSULTANT)
    r = await client.post(
        _submit(aid),
        headers=_hdr(USER_CONSULTANT),
        json=_project_publication_body(),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["submission_type"] == "submit_to_project" and body["status"] == "pending"
    assert body["review_task_id"] is not None
    assert "待项目经理确认" in body["message"]
    # review_task 真实落库，类型 personal_to_project。
    task = (
        await db_session.execute(
            select(ReviewTask).where(ReviewTask.id == uuid.UUID(body["review_task_id"]))
        )
    ).scalar_one()
    assert task.review_type == "personal_to_project"
    assert task.reviewer_user_id == USER_PROJECT_MANAGER  # ALPHA 的 active PM


async def test_project_approval_creates_independent_target_version_without_mutating_source(
    client, db_session
):
    source_id = await _mk_personal(db_session, owner=USER_CONSULTANT, zone="asset")
    source_before = await db_session.get(KnowledgeAsset, source_id)
    source_version_id = source_before.current_version_id
    source_canonical_name = source_before.canonical_name
    source_version_before = await db_session.get(KnowledgeAssetVersion, source_version_id)
    source_directory_key = source_version_before.directory_key
    submitted = await client.post(
        _submit(source_id),
        headers=_hdr(USER_CONSULTANT),
        json=_project_publication_body(),
    )
    assert submitted.status_code == 200, submitted.text

    approved = await client.post(
        f"/api/v1/reviews/{submitted.json()['review_task_id']}/approve",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={},
    )
    assert approved.status_code == 200, approved.text
    target_id = uuid.UUID(approved.json()["target_asset_id"])
    assert target_id != source_id

    db_session.expire_all()
    source = await db_session.get(KnowledgeAsset, source_id)
    target = await db_session.get(KnowledgeAsset, target_id)
    target_version = await db_session.get(KnowledgeAssetVersion, target.current_version_id)
    assert (source.scope, source.project_id, source.current_version_id) == (
        "personal",
        None,
        source_version_id,
    )
    assert source.canonical_name == source_canonical_name
    source_version_after = await db_session.get(KnowledgeAssetVersion, source.current_version_id)
    assert source_version_after.directory_key == source_directory_key
    assert (target.scope, target.project_id, target.source_asset_id) == (
        "project",
        PROJECT_ALPHA,
        source_id,
    )
    assert target.current_version_id != source_version_id
    assert target_version.directory_key == "project.deliverables"
    assert target_version.naming_rule_version == 10
    assert target.canonical_name.startswith("【ALPHA-2026-交付成果】")

    repeated = await client.post(
        _submit(source_id),
        headers=_hdr(USER_CONSULTANT),
        json=_project_publication_body(),
    )
    assert repeated.status_code == 200
    repeated_approval = await client.post(
        f"/api/v1/reviews/{repeated.json()['review_task_id']}/approve",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={},
    )
    assert repeated_approval.status_code == 200
    assert repeated_approval.json()["target_asset_id"] == str(target_id)
    derivative_count = await db_session.scalar(
        select(func.count())
        .select_from(KnowledgeAsset)
        .where(
            KnowledgeAsset.source_asset_id == source_id,
            KnowledgeAsset.scope == "project",
            KnowledgeAsset.project_id == PROJECT_ALPHA,
        )
    )
    assert derivative_count == 1


async def test_bulk_submit_requires_per_item_governed_naming(client, db_session):
    owned = await _mk_personal(db_session, owner=USER_CONSULTANT)
    not_owned = await _mk_personal(db_session, owner=USER_PROJECT_MANAGER)
    response = await client.post(
        "/api/v1/my/knowledge/bulk-submit-to-project",
        headers=_hdr(USER_CONSULTANT),
        json={
            "item_ids": [str(owned), str(not_owned)],
            "target_project_id": str(PROJECT_ALPHA),
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["denied_reason"] == "publication_naming_required"
    _assert_no_leak(response.text)


async def test_non_member_submit_forbidden(client, db_session):
    aid = await _mk_personal(db_session, owner=USER_CONSULTANT)
    # USER_CONSULTANT 在 BETA 为 inactive 成员 → 非 active 成员。
    r = await client.post(
        _submit(aid),
        headers=_hdr(USER_CONSULTANT),
        json=_project_publication_body(PROJECT_BETA),
    )
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "project_membership_required"


async def test_governance_without_project_membership_cannot_submit_personal(client, db_session):
    # 公司治理职务不自动授予项目知识提交权。
    aid = await _mk_personal(db_session, owner=USER_BOSS)
    r = await client.post(
        _submit(aid),
        headers=_hdr(USER_BOSS),
        json=_project_publication_body(),
    )
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "project_membership_required"


# ---------------- 幂等 / 去重 ----------------
async def test_idempotency_key_returns_same_submission(client, db_session):
    aid = await _mk_personal(db_session, owner=USER_CONSULTANT)
    key = "idem-personal-1"
    r1 = await client.post(
        _submit(aid),
        headers=_hdr(USER_CONSULTANT, **{"Idempotency-Key": key}),
        json=_project_publication_body(),
    )
    r2 = await client.post(
        _submit(aid),
        headers=_hdr(USER_CONSULTANT, **{"Idempotency-Key": key}),
        json=_project_publication_body(),
    )
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["submission_id"] == r2.json()["submission_id"]
    count = (
        await db_session.execute(
            select(func.count())
            .select_from(PersonalKnowledgeSubmission)
            .where(PersonalKnowledgeSubmission.source_asset_id == aid)
        )
    ).scalar_one()
    assert count == 1


async def test_no_key_pending_dedup(client, db_session):
    aid = await _mk_personal(db_session, owner=USER_CONSULTANT)
    r1 = await client.post(
        _submit(aid), headers=_hdr(USER_CONSULTANT), json=_project_publication_body()
    )
    r2 = await client.post(
        _submit(aid), headers=_hdr(USER_CONSULTANT), json=_project_publication_body()
    )
    assert r1.json()["submission_id"] == r2.json()["submission_id"]
    tasks = (
        await db_session.execute(
            select(func.count())
            .select_from(ReviewTask)
            .where(
                ReviewTask.target_asset_id == aid,
                ReviewTask.review_type == "personal_to_project",
            )
        )
    ).scalar_one()
    assert tasks == 1


# ---------------- 候选证据登记 ----------------
async def test_internal_sharing_candidate(client, db_session):
    aid = await _mk_personal(db_session, owner=USER_CONSULTANT)
    r = await client.post(
        _evidence(aid),
        headers=_hdr(USER_CONSULTANT),
        json={
            "target_project_id": str(PROJECT_ALPHA),
            "evidence_type": "internal_sharing",
            "evidence_category": "meeting_minutes",
            "description": "内部分享会纪要",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["submission_type"] == "internal_sharing_candidate"
    assert body["status"] == "pending"
    assert body["evidence_id"] is not None and body["review_task_id"] is not None
    # 文案不得表示已验证。
    assert "不自动证明" in body["message"]


async def test_client_validation_candidate(client, db_session):
    aid = await _mk_personal(db_session, owner=USER_CONSULTANT)
    r = await client.post(
        _evidence(aid),
        headers=_hdr(USER_CONSULTANT),
        json={
            "target_project_id": str(PROJECT_ALPHA),
            "evidence_type": "client_validation",
            "evidence_category": "client_email",
            "description": "客户确认邮件",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["submission_type"] == "client_validation_candidate"
    assert r.json()["evidence_id"] is not None


async def test_candidate_rejects_unsafe_attachment(client, db_session):
    aid = await _mk_personal(db_session, owner=USER_CONSULTANT)
    r = await client.post(
        _evidence(aid),
        headers=_hdr(USER_CONSULTANT),
        json={
            "target_project_id": str(PROJECT_ALPHA),
            "evidence_type": "internal_sharing",
            "evidence_category": "meeting_minutes",
            "attachments": [{"download_url": "https://evil.example/x"}],
        },
    )
    assert r.status_code == 422
    assert r.json()["detail"]["denied_reason"] == "attachment_metadata_forbidden"


# ---------------- 审计安全 ----------------
async def test_audit_no_leak(client, db_session):
    aid = await _mk_personal(db_session, owner=USER_CONSULTANT)
    await client.post(
        _evidence(aid),
        headers=_hdr(USER_CONSULTANT, **{"X-Trace-Id": "trc-personal-audit"}),
        json={
            "target_project_id": str(PROJECT_ALPHA),
            "evidence_type": "internal_sharing",
            "evidence_category": "meeting_minutes",
            "description": "纪要",
        },
    )
    rows = (
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.action.in_(["submission.created", "evidence.validation_registered"])
                )
            )
        )
        .scalars()
        .all()
    )
    assert rows
    blob = ""
    for ev in rows:
        blob += str(ev.extra) + str(ev.before_snapshot) + str(ev.after_snapshot)
    for t in _LEAK_TOKENS:
        assert t.lower() not in blob.lower()

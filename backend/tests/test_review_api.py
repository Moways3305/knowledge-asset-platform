"""审核流 API 测试（IMPLEMENT-06，material_to_asset 最小闭环）。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.models.audit import AuditEvent
from app.models.identity import UserCompanyRole
from app.models.knowledge import KnowledgeAsset
from app.models.review import CompanyAssetReviewDecision, ValidationEvidence
from app.schemas.enums import RoleStatus
from app.seed.dev_seed import (
    KA_PROJECT_ALPHA,
    KA_PROJECT_ALPHA_MATERIAL,
    PROJECT_ALPHA,
    PROJECT_BETA,
    REVIEW_SEED,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
    USER_PROJECT_MANAGER,
)

REVIEWS = "/api/v1/reviews"
KN = "/api/v1/knowledge"


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


def _evidence_body():
    return {
        "evidence_type": "internal_sharing",
        "evidence_category": "meeting_minutes",
        "description": "项目复盘会分享",
        "attachments": [{"name": "纪要", "note": "占位"}],
    }


def _confirm_url(project_id, asset_id):
    return f"/api/v1/projects/{project_id}/knowledge/{asset_id}/confirm-asset"


def _evidence_url(project_id, asset_id):
    return f"/api/v1/projects/{project_id}/knowledge/{asset_id}/evidence"


def _upgrade_url(project_id=PROJECT_ALPHA, asset_id=KA_PROJECT_ALPHA):
    return f"/api/v1/projects/{project_id}/knowledge/{asset_id}/upgrade-company"


async def test_confirm_asset_without_evidence_creates_pending_evidence(client):
    """consultant 对 material 资产发起 confirm-asset，无证据则 pending_evidence。"""
    resp = await client.post(
        _confirm_url(PROJECT_ALPHA, KA_PROJECT_ALPHA_MATERIAL),
        headers=_hdr(USER_CONSULTANT),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending_evidence"
    assert body["reviewer_user_id"] == str(USER_PROJECT_MANAGER)
    assert body["evidence_count"] == 0


async def test_full_loop_evidence_then_pm_approve_changes_zone(client):
    """登记证据 → pending_reviewer → PM approve → zone=asset，且 Knowledge API 可读到。"""
    # 发起 confirm-asset（pending_evidence）
    r1 = await client.post(
        _confirm_url(PROJECT_ALPHA, KA_PROJECT_ALPHA_MATERIAL), headers=_hdr(USER_CONSULTANT)
    )
    review_id = r1.json()["id"]
    # 登记证据 → 绑定并推进到 pending_reviewer
    r2 = await client.post(
        _evidence_url(PROJECT_ALPHA, KA_PROJECT_ALPHA_MATERIAL),
        headers=_hdr(USER_CONSULTANT),
        json=_evidence_body(),
    )
    assert r2.status_code == 200
    detail = (await client.get(f"{REVIEWS}/{review_id}", headers=_hdr(USER_CONSULTANT))).json()
    assert detail["status"] == "pending_reviewer"
    assert detail["evidence_count"] == 1
    # PM approve → approved + zone=asset
    r3 = await client.post(
        f"{REVIEWS}/{review_id}/approve",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={"review_comment": "确认有效"},
    )
    assert r3.status_code == 200
    assert r3.json()["status"] == "approved"
    assert r3.json()["asset_zone"] == "asset"
    # Knowledge detail 可读到 zone 变化
    d = (
        await client.get(f"{KN}/{KA_PROJECT_ALPHA_MATERIAL}", headers=_hdr(USER_PROJECT_MANAGER))
    ).json()
    assert d["zone"] == "asset"


async def test_reject_keeps_material(client):
    """reject 后 review=rejected，资产仍为 material。"""
    r1 = await client.post(
        _confirm_url(PROJECT_ALPHA, KA_PROJECT_ALPHA_MATERIAL), headers=_hdr(USER_CONSULTANT)
    )
    review_id = r1.json()["id"]
    await client.post(
        _evidence_url(PROJECT_ALPHA, KA_PROJECT_ALPHA_MATERIAL),
        headers=_hdr(USER_CONSULTANT),
        json=_evidence_body(),
    )
    r = await client.post(
        f"{REVIEWS}/{review_id}/reject",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={"review_comment": "证据不足"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    d = (
        await client.get(f"{KN}/{KA_PROJECT_ALPHA_MATERIAL}", headers=_hdr(USER_CONSULTANT))
    ).json()
    assert d["zone"] == "material"


async def test_non_reviewer_cannot_approve(client):
    """非 reviewer（提交人 consultant）approve 返回 403。"""
    r1 = await client.post(
        _confirm_url(PROJECT_ALPHA, KA_PROJECT_ALPHA_MATERIAL), headers=_hdr(USER_CONSULTANT)
    )
    review_id = r1.json()["id"]
    await client.post(
        _evidence_url(PROJECT_ALPHA, KA_PROJECT_ALPHA_MATERIAL),
        headers=_hdr(USER_CONSULTANT),
        json=_evidence_body(),
    )
    r = await client.post(f"{REVIEWS}/{review_id}/approve", headers=_hdr(USER_CONSULTANT), json={})
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "review_action_forbidden"


async def test_double_finalize_returns_409(client):
    """终态重复 approve 返回 409。"""
    r1 = await client.post(
        _confirm_url(PROJECT_ALPHA, KA_PROJECT_ALPHA_MATERIAL), headers=_hdr(USER_CONSULTANT)
    )
    review_id = r1.json()["id"]
    await client.post(
        _evidence_url(PROJECT_ALPHA, KA_PROJECT_ALPHA_MATERIAL),
        headers=_hdr(USER_CONSULTANT),
        json=_evidence_body(),
    )
    await client.post(f"{REVIEWS}/{review_id}/approve", headers=_hdr(USER_PROJECT_MANAGER), json={})
    r = await client.post(
        f"{REVIEWS}/{review_id}/approve", headers=_hdr(USER_PROJECT_MANAGER), json={}
    )
    assert r.status_code == 409
    assert r.json()["detail"]["denied_reason"] == "review_already_finalized"


async def test_approve_without_evidence_422(client):
    """无证据 approve 返回 422 review_evidence_required。"""
    r1 = await client.post(
        _confirm_url(PROJECT_ALPHA, KA_PROJECT_ALPHA_MATERIAL), headers=_hdr(USER_CONSULTANT)
    )
    review_id = r1.json()["id"]  # pending_evidence，无证据
    r = await client.post(
        f"{REVIEWS}/{review_id}/approve", headers=_hdr(USER_PROJECT_MANAGER), json={}
    )
    assert r.status_code == 422
    assert r.json()["detail"]["denied_reason"] == "review_evidence_required"


async def test_admin_reviews_403(client):
    """纯 admin 访问审核队列返回 403。"""
    resp = await client.get(REVIEWS, headers=_hdr(USER_ADMIN_ONLY))
    assert resp.status_code == 403
    assert resp.json()["detail"]["denied_reason"] == "admin_business_permission_denied"


async def test_non_member_cannot_register_evidence_or_confirm(client):
    """非项目成员（consultant 对 Beta）不能登记证据或发起 confirm-asset。"""
    # consultant 在 Beta 为 inactive 成员 → 非 active member
    r_ev = await client.post(
        _evidence_url(PROJECT_BETA, KA_PROJECT_ALPHA_MATERIAL),
        headers=_hdr(USER_CONSULTANT),
        json=_evidence_body(),
    )
    assert r_ev.status_code == 403
    assert r_ev.json()["detail"]["denied_reason"] == "project_membership_required"
    # confirm-asset 同样被拒
    r_cf = await client.post(
        _confirm_url(PROJECT_BETA, KA_PROJECT_ALPHA_MATERIAL),
        headers=_hdr(USER_CONSULTANT),
    )
    assert r_cf.status_code == 403
    assert r_cf.json()["detail"]["denied_reason"] == "project_membership_required"


async def test_admin_approve_reject_forbidden(client):
    """纯 admin 调用 approve / reject 返回 403 admin_business_permission_denied。"""
    rid = str(REVIEW_SEED)  # seed 的 pending_reviewer 任务
    r_ap = await client.post(f"{REVIEWS}/{rid}/approve", headers=_hdr(USER_ADMIN_ONLY), json={})
    assert r_ap.status_code == 403
    assert r_ap.json()["detail"]["denied_reason"] == "admin_business_permission_denied"
    r_rj = await client.post(
        f"{REVIEWS}/{rid}/reject", headers=_hdr(USER_ADMIN_ONLY), json={"review_comment": "x"}
    )
    assert r_rj.status_code == 403
    assert r_rj.json()["detail"]["denied_reason"] == "admin_business_permission_denied"


async def test_evidence_illegal_attachments_422_not_created(client, db_session):
    """附件 metadata 携带真实 URL/路径/内部引用 → 422，且不创建 evidence。"""
    before = await db_session.scalar(select(func.count()).select_from(ValidationEvidence))
    bad = {
        "evidence_type": "internal_sharing",
        "evidence_category": "meeting_minutes",
        "description": "非法附件",
        "attachments": [{"download_url": "https://example.com/x.pdf"}],
    }
    r = await client.post(
        _evidence_url(PROJECT_ALPHA, KA_PROJECT_ALPHA_MATERIAL),
        headers=_hdr(USER_CONSULTANT),
        json=bad,
    )
    assert r.status_code == 422
    after = await db_session.scalar(select(func.count()).select_from(ValidationEvidence))
    assert after == before  # 未创建任何 evidence


async def test_reviews_list_no_internal_fields(client):
    """审核队列响应不泄露 storage_ref / source_file_ref / 真实附件 URL。"""
    resp = await client.get(REVIEWS, headers=_hdr(USER_PROJECT_MANAGER))
    assert resp.status_code == 200
    assert "storage_ref" not in resp.text
    assert "source_file_ref" not in resp.text
    # seed 的 pending_reviewer 审核任务（分配给经理 B）可见
    assert resp.json()["total"] >= 1


async def test_governance_sees_reviews(client):
    """boss（治理角色）可看审核队列。"""
    resp = await client.get(REVIEWS, headers=_hdr(USER_BOSS))
    assert resp.status_code == 200


async def test_company_upgrade_requires_independent_general_manager_and_director(
    client, db_session
):
    created = await client.post(_upgrade_url(), headers=_hdr(USER_PROJECT_MANAGER))
    assert created.status_code == 200, created.text
    review_id = created.json()["id"]

    first = await client.post(
        f"{REVIEWS}/{review_id}/approve",
        headers=_hdr(USER_BOSS),
        json={"review_comment": "总经理确认"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "pending_reviewer"
    detail = await client.get(f"{REVIEWS}/{review_id}", headers=_hdr(USER_BOSS))
    assert detail.json()["general_manager_confirmation_status"] == "confirmed"
    assert detail.json()["consulting_director_confirmation_status"] is None

    second = await client.post(
        f"{REVIEWS}/{review_id}/approve",
        headers=_hdr(USER_DIRECTOR),
        json={"review_comment": "咨询总监确认"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "approved"
    db_session.expire_all()
    asset = await db_session.get(KnowledgeAsset, KA_PROJECT_ALPHA)
    assert asset.scope == "company"
    assert asset.project_id is None

    decisions = list(
        (
            await db_session.execute(
                select(CompanyAssetReviewDecision).where(
                    CompanyAssetReviewDecision.review_task_id == uuid.UUID(review_id)
                )
            )
        )
        .scalars()
        .all()
    )
    assert {(row.required_role, row.actor_user_id) for row in decisions} == {
        ("boss", USER_BOSS),
        ("consulting_director", USER_DIRECTOR),
    }
    audits = list(
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.target_id == KA_PROJECT_ALPHA)
            )
        )
        .scalars()
        .all()
    )
    assert "asset.scope_changed" in {row.action for row in audits}


async def test_same_person_cannot_fill_both_company_confirmation_roles(client, db_session):
    db_session.add(
        UserCompanyRole(
            user_id=USER_BOSS,
            company_role="consulting_director",
            status=RoleStatus.active.value,
        )
    )
    await db_session.commit()
    created = await client.post(_upgrade_url(), headers=_hdr(USER_PROJECT_MANAGER))
    review_id = created.json()["id"]
    first = await client.post(f"{REVIEWS}/{review_id}/approve", headers=_hdr(USER_BOSS), json={})
    assert first.status_code == 200
    second = await client.post(f"{REVIEWS}/{review_id}/approve", headers=_hdr(USER_BOSS), json={})
    assert second.status_code == 403
    assert second.json()["detail"]["denied_reason"] == "company_confirmation_role_required"


async def test_company_upgrade_reject_and_withdraw_are_terminal(client, db_session):
    created = await client.post(_upgrade_url(), headers=_hdr(USER_PROJECT_MANAGER))
    review_id = created.json()["id"]
    rejected = await client.post(
        f"{REVIEWS}/{review_id}/reject",
        headers=_hdr(USER_DIRECTOR),
        json={"review_comment": "不适合公司复用"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    asset = await db_session.get(KnowledgeAsset, KA_PROJECT_ALPHA)
    assert asset.scope == "project"

    # 终态后可重新发起一个独立审核；已拒绝历史保留。
    retry = await client.post(_upgrade_url(), headers=_hdr(USER_PROJECT_MANAGER))
    retry_id = retry.json()["id"]
    await client.post(f"{REVIEWS}/{retry_id}/approve", headers=_hdr(USER_BOSS), json={})
    withdrawn = await client.post(
        f"{REVIEWS}/{retry_id}/withdraw",
        headers=_hdr(USER_BOSS),
        json={"review_comment": "撤回确认"},
    )
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "rejected"
    assert (
        await client.post(f"{REVIEWS}/{retry_id}/approve", headers=_hdr(USER_DIRECTOR), json={})
    ).status_code == 409


async def test_missing_director_keeps_company_upgrade_pending(client, db_session):
    role = (
        await db_session.execute(
            select(UserCompanyRole).where(
                UserCompanyRole.user_id == USER_DIRECTOR,
                UserCompanyRole.company_role == "consulting_director",
            )
        )
    ).scalar_one()
    role.status = RoleStatus.inactive.value
    await db_session.commit()

    created = await client.post(_upgrade_url(), headers=_hdr(USER_PROJECT_MANAGER))
    review_id = created.json()["id"]
    confirmed = await client.post(
        f"{REVIEWS}/{review_id}/approve", headers=_hdr(USER_BOSS), json={}
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "pending_reviewer"
    asset = await db_session.get(KnowledgeAsset, KA_PROJECT_ALPHA)
    assert asset.scope == "project"


async def test_admin_and_company_role_cannot_bypass_project_confirmation(client):
    created = await client.post(_upgrade_url(), headers=_hdr(USER_ADMIN_ONLY))
    assert created.status_code == 403
    review = await client.post(
        f"{REVIEWS}/{REVIEW_SEED}/approve", headers=_hdr(USER_DIRECTOR), json={}
    )
    assert review.status_code == 403
    assert review.json()["detail"]["denied_reason"] == "review_action_forbidden"

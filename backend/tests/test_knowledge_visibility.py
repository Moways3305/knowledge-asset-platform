"""知识可见性权限收口测试。

核心：纯系统身份（仅 admin，is_business_user=false）不经知识发现路径浏览任何业务知识
（列表 / 详情 / 搜索 / 预览 / 项目 QA / Agent 召回），fail-closed 不泄露存在性。
同时验证既有业务身份可见性（项目 active 成员、个人 owner、公司治理）不被误伤，
inactive 项目成员不获得成员级（原文）访问。
"""

from __future__ import annotations

from app.models.knowledge import KnowledgeAsset
from app.schemas.permission import AccessLayer, DeniedReason
from app.seed.dev_seed import (
    KA_COMPANY_L2,
    KA_COMPANY_L4,
    KA_PERSONAL,
    KA_PROJECT_ALPHA,
    KA_PROJECT_BETA_L3,
    PROJECT_ALPHA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_PROJECT_MANAGER,
)
from app.services.permission import build_caller_context, decide

KN = "/api/v1/knowledge"
SEARCH = "/api/v1/knowledge/search"


def _hdr(uid):
    return {"X-Dev-User-Id": str(uid)}


# ================= 纯 admin（非业务身份）不见任何业务知识 =================
async def test_admin_knowledge_list_excludes_all_business_assets(client):
    for scope, directory in (
        ("company", "company.methodology"),
        ("personal", "personal.learning_notes"),
    ):
        url = f"{KN}?scope={scope}&directory_key={directory}"
        resp = await client.get(url, headers=_hdr(USER_ADMIN_ONLY))
        assert resp.status_code == 200
        assert resp.json()["items"] == [], f"admin 不应在 {scope} 列表看到任何业务资产"


async def test_admin_knowledge_detail_404(client):
    for aid in (KA_COMPANY_L2, KA_COMPANY_L4, KA_PROJECT_ALPHA, KA_PROJECT_BETA_L3, KA_PERSONAL):
        resp = await client.get(f"{KN}/{aid}", headers=_hdr(USER_ADMIN_ONLY))
        assert resp.status_code == 404, f"admin 详情 {aid} 应 404 不泄露"
        assert resp.json()["detail"]["denied_reason"] == "knowledge_asset_not_found"


async def test_admin_search_returns_no_cards(client):
    resp = await client.post(
        SEARCH, headers=_hdr(USER_ADMIN_ONLY), json={"query": "数字化", "scope": "all"}
    )
    assert resp.status_code == 200
    assert resp.json()["cards"] == []


async def test_admin_preview_denied(client):
    resp = await client.post(f"{KN}/{KA_COMPANY_L2}/preview", headers=_hdr(USER_ADMIN_ONLY))
    assert resp.status_code in (403, 404)


async def test_admin_decide_all_layers_denied(db_session):
    """权限内核层面：admin 对各类资产连发现层都不可达，原因 business_identity_required。"""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.identity import User

    admin = (
        await db_session.execute(
            select(User)
            .where(User.id == USER_ADMIN_ONLY)
            .options(selectinload(User.company_roles), selectinload(User.project_members))
        )
    ).scalar_one()
    ctx = build_caller_context(admin)
    assert ctx.is_business_user is False
    for aid in (KA_COMPANY_L2, KA_PROJECT_ALPHA, KA_PERSONAL):
        asset = await db_session.get(KnowledgeAsset, aid)
        d = decide(ctx, asset, AccessLayer.discovery)
        assert d.allowed is False
        assert d.denied_reason == DeniedReason.business_identity_required


# ================= 业务身份可见性不被误伤 =================
async def test_project_active_member_sees_own_project_asset(client):
    # 顾问 A 是 Alpha active 成员 → 可见 Alpha 项目资产（发现 + 原文）。
    resp = await client.get(f"{KN}/{KA_PROJECT_ALPHA}", headers=_hdr(USER_CONSULTANT))
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_info"]["discovery"] is True
    assert body["access_info"]["original"] is True
    assert body["access_info"]["effective_source"] == "project_member"


async def test_personal_owner_sees_own_others_404(client):
    # owner 可见个人知识；他人（经理 B）404 不泄露。
    assert (
        await client.get(f"{KN}/{KA_PERSONAL}", headers=_hdr(USER_CONSULTANT))
    ).status_code == 200
    assert (
        await client.get(f"{KN}/{KA_PERSONAL}", headers=_hdr(USER_PROJECT_MANAGER))
    ).status_code == 404


async def test_governance_company_visibility_preserved(client):
    # boss 公司治理可见性保持：公司 L2 可发现 + 摘要（不被可见性收口误伤）。
    resp = await client.get(f"{KN}/{KA_COMPANY_L2}", headers=_hdr(USER_BOSS))
    assert resp.status_code == 200
    assert resp.json()["access_info"]["discovery"] is True
    assert resp.json()["access_info"]["summary"] is True


async def test_inactive_project_member_gets_cross_project_summary_not_member_original(db_session):
    """inactive 关系不产生成员原文权，但 active 业务身份仍可读跨项目安全摘要。"""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.identity import User

    consultant = (
        await db_session.execute(
            select(User)
            .where(User.id == USER_CONSULTANT)
            .options(selectinload(User.company_roles), selectinload(User.project_members))
        )
    ).scalar_one()
    ctx = build_caller_context(consultant)
    assert PROJECT_ALPHA in ctx.active_project_ids  # Alpha active
    # Beta 不在 active 集合（inactive 成员关系不计入）。
    beta_l3 = await db_session.get(KnowledgeAsset, KA_PROJECT_BETA_L3)
    assert beta_l3.project_id not in ctx.active_project_ids
    orig = decide(ctx, beta_l3, AccessLayer.original)
    assert orig.allowed is False
    assert orig.denied_reason == DeniedReason.original_requires_request
    summ = decide(ctx, beta_l3, AccessLayer.summary)
    assert summ.allowed is True
    assert summ.summary_variant == "redacted_summary"

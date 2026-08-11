"""Knowledge 读 API 测试（IMPLEMENT-04）。

覆盖：列表可发现过滤、L5 发现边界、他人 personal 过滤、my/knowledge owner 与
admin 403、L3/L4 详情 original=false + 脱敏摘要、项目成员/非成员、archived 默认不返回、
storage_ref 不外泄。
"""

from __future__ import annotations

from app.models.knowledge import KnowledgeAsset
from app.seed.dev_seed import (
    KA_COMPANY_L4,
    KA_COMPANY_L5,
    KA_PROJECT_BETA_L3,
    PROJECT_ALPHA,
    PROJECT_BETA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
)

KN = "/api/v1/knowledge"
MY = "/api/v1/my/knowledge"


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


async def test_list_default_user_no_storage_ref(client):
    """默认用户可获取列表，且响应中不出现 storage_ref。"""
    resp = await client.get(KN)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert "storage_ref" not in resp.text


async def test_consultant_cannot_see_l5_but_boss_can(client):
    """consultant 列表不含 L5；boss 列表包含 L5。"""
    consultant_titles = {
        i["title"] for i in (await client.get(KN, headers=_hdr(USER_CONSULTANT))).json()["items"]
    }
    boss_titles = {
        i["title"] for i in (await client.get(KN, headers=_hdr(USER_BOSS))).json()["items"]
    }
    assert "公司级绝密战略备忘" not in consultant_titles
    assert "公司级绝密战略备忘" in boss_titles


async def test_others_personal_not_in_list_but_owner_in_my(client):
    """他人 personal 不出现在 boss 的列表；owner 的 /my/knowledge 能看到自己的。"""
    # boss 看公司列表不应出现 consultant 的个人草稿。
    boss_titles = {
        i["title"] for i in (await client.get(KN, headers=_hdr(USER_BOSS))).json()["items"]
    }
    assert "个人方法论草稿" not in boss_titles
    # owner（consultant）的 my/knowledge 能看到自己的个人草稿。
    my = (await client.get(MY, headers=_hdr(USER_CONSULTANT))).json()
    assert any(i["title"] == "个人方法论草稿" for i in my["items"])
    assert all(i["scope"] == "personal" for i in my["items"])


async def test_admin_my_knowledge_403(client):
    """纯 admin 请求 /my/knowledge 返回 403 + admin_business_permission_denied。"""
    resp = await client.get(MY, headers=_hdr(USER_ADMIN_ONLY))
    assert resp.status_code == 403
    assert resp.json()["detail"]["denied_reason"] == "admin_business_permission_denied"


async def test_l4_detail_original_false_and_redacted_summary(client):
    """L4 详情：access_info.original=false，摘要为脱敏口径。"""
    resp = await client.get(f"{KN}/{KA_COMPANY_L4}", headers=_hdr(USER_CONSULTANT))
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_info"]["discovery"] is True
    assert body["access_info"]["summary"] is True
    assert body["access_info"]["original"] is False
    assert body["access_info"]["can_request_original"] is True
    # 摘要应为脱敏文本（seed 中以"（脱敏）"开头），且无 key_points 泄露。
    assert body["summary"]["one_liner"].startswith("（脱敏）")
    assert body["summary"]["key_points"] == []


async def test_l5_detail_404_for_consultant(client):
    """L5 详情对 consultant 返回 404（不泄露存在）。"""
    resp = await client.get(f"{KN}/{KA_COMPANY_L5}", headers=_hdr(USER_CONSULTANT))
    assert resp.status_code == 404


async def test_project_non_member_l3_gets_only_redacted_summary_projection(client):
    """consultant 非 Beta active 成员，可发现但只能读取脱敏摘要和安全卡片字段。"""
    resp = await client.get(f"{KN}/{KA_PROJECT_BETA_L3}", headers=_hdr(USER_CONSULTANT))
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_info"]["cross_project_summary"] is True
    assert body["access_info"]["summary"] is True
    assert body["access_info"]["original"] is False
    assert body["access_info"]["can_request_original"] is True
    assert body["summary"]["detailed"].startswith("（脱敏）")
    assert body["summary"]["key_points"] == []
    assert body["maintainer"] is None
    assert body["current_version"] is None
    assert body["canonical_markdown_status"] is None
    assert body["index_status"] is None
    assert body["weknora_parse_status"] is None
    assert body["index_error_message"] is None
    for forbidden in ("storage_ref", "source_file_ref", "weknora_kb_id", "weknora_doc_id"):
        assert forbidden not in resp.text


async def test_project_member_can_get_original(client):
    """consultant 是 Alpha active 成员：Alpha 项目资产 original=true。"""
    items = (await client.get(f"{KN}?scope=project", headers=_hdr(USER_CONSULTANT))).json()["items"]
    alpha = next(i for i in items if i["title"].startswith("Alpha 项目"))
    assert alpha["access_info"]["original"] is True


async def test_project_list_uses_exact_authorized_project_id(client):
    response = await client.get(
        f"{KN}?scope=project&project_id={PROJECT_ALPHA}", headers=_hdr(USER_CONSULTANT)
    )
    assert response.status_code == 200
    assert response.json()["items"]
    assert all(item["project_name"] == "Alpha 项目" for item in response.json()["items"])

    denied = await client.get(
        f"{KN}?scope=project&project_id={PROJECT_BETA}", headers=_hdr(USER_CONSULTANT)
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["denied_reason"] == "project_membership_required"


async def test_project_id_filter_rejects_non_project_scope(client):
    response = await client.get(
        f"{KN}?scope=company&project_id={PROJECT_ALPHA}", headers=_hdr(USER_CONSULTANT)
    )
    assert response.status_code == 422
    assert response.json()["detail"]["denied_reason"] == "project_filter_scope_mismatch"


async def test_archived_not_in_default_list(client):
    """archived 资产默认不在列表中返回。"""
    titles = {i["title"] for i in (await client.get(KN, headers=_hdr(USER_BOSS))).json()["items"]}
    assert "已归档的旧组织诊断指南" not in titles


async def test_my_knowledge_excludes_owner_archived_personal(client, db_session):
    """本人已归档的 personal 资产默认不出现在 /my/knowledge（与权限读侧口径一致）。"""
    archived = KnowledgeAsset(
        title="本人已归档草稿",
        scope="personal",
        zone="material",
        asset_type="methodology",
        owner_user_id=USER_CONSULTANT,
        visibility="confidential",
        confidentiality_level="L2",
        ai_access_level="A1",
        asset_status="archived",
    )
    db_session.add(archived)
    await db_session.commit()

    resp = await client.get(MY, headers=_hdr(USER_CONSULTANT))
    assert resp.status_code == 200
    titles = [i["title"] for i in resp.json()["items"]]
    assert "本人已归档草稿" not in titles  # archived 被读侧过滤
    assert "个人方法论草稿" in titles  # active 个人资产仍在


async def test_health_and_auth_still_work(client):
    """既有 /health 与 /auth/me 仍可用（回归）。"""
    assert (await client.get("/health")).status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=_hdr(USER_CONSULTANT))).status_code == 200

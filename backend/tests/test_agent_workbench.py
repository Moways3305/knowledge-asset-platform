"""WorkBuddy 只读工作台 agent-gateway 端点测试（PBC-37）。

覆盖：安全字段返回、caller 仅由 token 绑定解析、伪造 user id 不生效、无权项目/资产不泄露
存在性、L5 / 他人 personal / 原文层边界不回归、token 天花板标题收口、no-leak。
"""

from __future__ import annotations

import uuid

from app.models.agent_registry import AgentWhitelistRule
from app.models.original_access import OriginalAccessRequest
from app.seed.dev_seed import (
    KA_COMPANY_L2,
    KA_COMPANY_L4,
    KA_COMPANY_L5,
    KA_PERSONAL,
    KA_PROJECT_ALPHA,
    KA_PROJECT_ALPHA_L5,
    PROJECT_ALPHA,
    PROJECT_BETA,
    USER_BOSS,
    USER_CONSULTANT,
    USER_PROJECT_MANAGER,
)
from app.services.agent_registry import hash_token

TODOS = "/api/v1/agent-gateway/todos"
RECENT = "/api/v1/agent-gateway/knowledge/recent"
PROJECTS = "/api/v1/agent-gateway"  # + /projects/{id}/knowledge|brief
REVIEWS = "/api/v1/agent-gateway/reviews/pending"
OAR = "/api/v1/agent-gateway/original-access/requests"

_TOKEN = "kgw_workbench_token"

# response 中绝不应出现的安全红线（响应字段 / 值）。
_LEAK_TOKENS = [
    "storage_ref",
    "source_file_ref",
    "download_url",
    "preview_entry_url",
    "weknora_kb_id",
    "weknora_doc_id",
    "chunk_id",
    "dataset_id",
    "workflow_id",
    "token_hash",
    "api_key",
    "app_secret",
    "access_token",
    "kap_session",
    "wk-kb",
    "wk-doc",
]


async def _insert_rule(
    db_session,
    *,
    token=_TOKEN,
    bound_user_id=USER_CONSULTANT,
    enabled=True,
    capability="qa",
    max_conf="L5",
):
    rule = AgentWhitelistRule(
        provider="workbuddy",
        agent_identifier=f"wb-{uuid.uuid4().hex[:8]}",
        agent_name="WorkBuddy 工作台测试",
        capability=capability,
        allowed_scope=None,
        max_confidentiality_level=max_conf,
        max_ai_access_level="A4",
        token_hash=hash_token(token),
        enabled=enabled,
        bound_user_id=bound_user_id,
    )
    db_session.add(rule)
    await db_session.commit()
    return rule


def _bearer(token=_TOKEN):
    return {"Authorization": f"Bearer {token}"}


def _no_leak(text: str):
    for t in _LEAK_TOKENS:
        assert t not in text, f"leak token {t!r} present in response"


# ---------------------------------------------------------------------------
# auth / binding
# ---------------------------------------------------------------------------
async def test_todos_missing_bearer_rejected(client, db_session):
    await _insert_rule(db_session)
    r = await client.get(TODOS)
    assert r.status_code == 401


async def test_unbound_token_fails_closed(client, db_session):
    await _insert_rule(db_session, bound_user_id=None)
    r = await client.get(RECENT, headers=_bearer())
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "caller_unbound"


async def test_client_supplied_user_id_ignored(client, db_session):
    """带伪造 X-Platform-User-Id / query user_id 都不改变 caller（仍为绑定用户）。"""
    await _insert_rule(db_session, bound_user_id=USER_CONSULTANT)
    r = await client.get(
        RECENT,
        headers={**_bearer(), "X-Platform-User-Id": str(USER_BOSS)},
        params={"scope": "company", "user_id": str(USER_BOSS)},
    )
    assert r.status_code == 200
    ids = {c["asset_id"] for c in r.json()["items"]}
    # 绑定用户是 consultant：可见 company L2，但不可发现 company L5（伪造 boss 身份无效）。
    assert str(KA_COMPANY_L2) in ids
    assert str(KA_COMPANY_L5) not in ids


# ---------------------------------------------------------------------------
# recent knowledge
# ---------------------------------------------------------------------------
async def test_recent_company_safe_fields(client, db_session):
    await _insert_rule(db_session)
    r = await client.get(RECENT, headers=_bearer(), params={"scope": "company"})
    assert r.status_code == 200, r.text
    body = r.json()
    item = next(c for c in body["items"] if c["asset_id"] == str(KA_COMPANY_L2))
    assert set(item.keys()) == {
        "asset_id",
        "title",
        "scope",
        "zone",
        "asset_type",
        "confidentiality_level",
        "one_liner",
        "updated_at",
        "project_id",
        "project_name",
        "can_view_original",
    }
    _no_leak(r.text)


async def test_recent_consultant_cannot_see_l5(client, db_session):
    await _insert_rule(db_session)
    r = await client.get(RECENT, headers=_bearer(), params={"scope": "company"})
    ids = {c["asset_id"] for c in r.json()["items"]}
    assert str(KA_COMPANY_L5) not in ids


# ---------------------------------------------------------------------------
# knowledge summary
# ---------------------------------------------------------------------------
async def test_summary_returns_safe_summary(client, db_session):
    await _insert_rule(db_session)
    r = await client.get(
        f"/api/v1/agent-gateway/knowledge/{KA_COMPANY_L2}/summary", headers=_bearer()
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["asset_id"] == str(KA_COMPANY_L2)
    assert body["access_layer"] in ("discovery", "summary", "original")
    assert "summary" in body and "key_points" in body
    _no_leak(r.text)


async def test_summary_l5_not_discoverable_returns_404(client, db_session):
    """consultant 对 company L5 不可发现：404，不泄露存在性。"""
    await _insert_rule(db_session)
    r = await client.get(
        f"/api/v1/agent-gateway/knowledge/{KA_COMPANY_L5}/summary", headers=_bearer()
    )
    assert r.status_code == 404


async def test_summary_owner_personal_ok(client, db_session):
    await _insert_rule(db_session, bound_user_id=USER_CONSULTANT)
    r = await client.get(
        f"/api/v1/agent-gateway/knowledge/{KA_PERSONAL}/summary", headers=_bearer()
    )
    assert r.status_code == 200


async def test_summary_others_personal_not_discoverable(client, db_session):
    """绑定到 boss（非 KA_PERSONAL owner）：他人个人知识不可发现 → 404。"""
    await _insert_rule(db_session, bound_user_id=USER_BOSS)
    r = await client.get(
        f"/api/v1/agent-gateway/knowledge/{KA_PERSONAL}/summary", headers=_bearer()
    )
    assert r.status_code == 404


async def test_summary_token_ceiling_hides_high_conf(client, db_session):
    """token 天花板 L2：即便绑定用户 (boss) 可发现 company L4，也被天花板收口为 404。"""
    await _insert_rule(db_session, bound_user_id=USER_BOSS, max_conf="L2")
    r = await client.get(
        f"/api/v1/agent-gateway/knowledge/{KA_COMPANY_L4}/summary", headers=_bearer()
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# project knowledge / brief
# ---------------------------------------------------------------------------
async def test_project_knowledge_member_ok_excludes_l5(client, db_session):
    await _insert_rule(db_session, bound_user_id=USER_CONSULTANT)
    r = await client.get(
        f"/api/v1/agent-gateway/projects/{PROJECT_ALPHA}/knowledge", headers=_bearer()
    )
    assert r.status_code == 200, r.text
    ids = {c["asset_id"] for c in r.json()["items"]}
    assert str(KA_PROJECT_ALPHA) in ids
    assert str(KA_PROJECT_ALPHA_L5) not in ids
    _no_leak(r.text)


async def test_project_knowledge_non_member_not_enumerable(client, db_session):
    """consultant_a 非 Beta active 成员、非治理 → 无权项目与不存在项目不可区分（统一 404）。"""
    await _insert_rule(db_session, bound_user_id=USER_CONSULTANT)
    no_access = await client.get(
        f"/api/v1/agent-gateway/projects/{PROJECT_BETA}/knowledge", headers=_bearer()
    )
    missing = await client.get(
        f"/api/v1/agent-gateway/projects/{uuid.uuid4()}/knowledge", headers=_bearer()
    )
    assert no_access.status_code == 404
    assert missing.status_code == 404
    # 错误形态完全一致：无法据此区分 Beta 是否真实存在。
    assert no_access.json() == missing.json()
    # 不泄露项目名 / 客户 / 成员 / 权限原因。
    text = no_access.text
    for leak in ("Beta 项目", "membership", "project_membership_required", "client", "成员"):
        assert leak not in text
    _no_leak(text)


async def test_project_knowledge_governance_without_membership_is_hidden(client, db_session):
    await _insert_rule(db_session, bound_user_id=USER_BOSS)
    r = await client.get(
        f"/api/v1/agent-gateway/projects/{PROJECT_BETA}/knowledge", headers=_bearer()
    )
    assert r.status_code == 404
    assert r.json()["detail"]["denied_reason"] == "project_not_found"


async def test_project_knowledge_unknown_project_404(client, db_session):
    await _insert_rule(db_session)
    r = await client.get(
        f"/api/v1/agent-gateway/projects/{uuid.uuid4()}/knowledge", headers=_bearer()
    )
    assert r.status_code == 404


async def test_project_brief_member(client, db_session):
    await _insert_rule(db_session, bound_user_id=USER_CONSULTANT)
    r = await client.get(f"/api/v1/agent-gateway/projects/{PROJECT_ALPHA}/brief", headers=_bearer())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["project_id"] == str(PROJECT_ALPHA)
    assert body["my_role"] == "consultant"
    assert set(body.keys()) == {
        "project_id",
        "name",
        "status",
        "phase",
        "my_role",
        "knowledge_count",
        "recent_asset_count",
        "pending_review_count",
        "pending_original_request_count",
    }
    assert "client_name" not in r.text
    _no_leak(r.text)


async def test_project_brief_non_member_not_enumerable(client, db_session):
    """brief 同样把无权项目与不存在项目统一为 404，不可枚举。"""
    await _insert_rule(db_session, bound_user_id=USER_CONSULTANT)
    no_access = await client.get(
        f"/api/v1/agent-gateway/projects/{PROJECT_BETA}/brief", headers=_bearer()
    )
    missing = await client.get(
        f"/api/v1/agent-gateway/projects/{uuid.uuid4()}/brief", headers=_bearer()
    )
    assert no_access.status_code == 404
    assert missing.status_code == 404
    assert no_access.json() == missing.json()
    for leak in ("Beta 项目", "membership", "project_membership_required", "client", "成员"):
        assert leak not in no_access.text
    _no_leak(no_access.text)


# ---------------------------------------------------------------------------
# todos / reviews
# ---------------------------------------------------------------------------
async def test_todos_reviewer_sees_pending_review(client, db_session):
    """经理 B 是 seed review 的 reviewer（pending_reviewer）→ todos 含 review 项。"""
    await _insert_rule(db_session, bound_user_id=USER_PROJECT_MANAGER)
    r = await client.get(TODOS, headers=_bearer())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counts"]["reviews"] >= 1
    assert any(i["type"] == "review" for i in body["items"])
    _no_leak(r.text)


async def test_reviews_pending_visible_to_submitter(client, db_session):
    """consultant_a 是 seed review 提交人 → reviews/pending 可见该项。"""
    await _insert_rule(db_session, bound_user_id=USER_CONSULTANT)
    r = await client.get(REVIEWS, headers=_bearer())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    item = body["items"][0]
    assert set(item.keys()) == {
        "review_id",
        "review_type",
        "status",
        "asset_id",
        "asset_title",
        "project_id",
        "project_name",
        "created_at",
        "due_hint",
    }
    _no_leak(r.text)


# ---------------------------------------------------------------------------
# original-access
# ---------------------------------------------------------------------------
async def _seed_request(db_session, *, requester, asset_id, project_id=None, reason="需要原文核对"):
    req = OriginalAccessRequest(
        asset_id=asset_id,
        requester_user_id=requester,
        project_id=project_id,
        requested_access_layer="original",
        reason=reason,
        status="pending",
    )
    db_session.add(req)
    await db_session.commit()
    return req


async def test_original_access_mine_lists_request(client, db_session):
    await _insert_rule(db_session, bound_user_id=USER_CONSULTANT)
    await _seed_request(db_session, requester=USER_CONSULTANT, asset_id=KA_COMPANY_L4)
    r = await client.get(OAR, headers=_bearer(), params={"box": "mine"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 1
    item = body["items"][0]
    assert item["box"] == "mine"
    assert set(item.keys()) == {
        "request_id",
        "box",
        "status",
        "asset_id",
        "asset_title",
        "requester_name",
        "reviewer_name",
        "reason",
        "created_at",
        "reviewed_at",
        "expires_at",
    }
    _no_leak(r.text)


async def test_original_access_ceiling_masks_title(client, db_session):
    """L2 天花板 token：mine 申请指向 L4 资产 → 标题被安全占位收口。"""
    await _insert_rule(db_session, bound_user_id=USER_CONSULTANT, max_conf="L2")
    await _seed_request(db_session, requester=USER_CONSULTANT, asset_id=KA_COMPANY_L4)
    r = await client.get(OAR, headers=_bearer(), params={"box": "mine"})
    assert r.status_code == 200
    titles = {it["asset_title"] for it in r.json()["items"]}
    assert "医药集采渠道影响分析" not in titles
    assert "（受限知识）" in titles


async def test_original_access_invalid_box_defaults_mine(client, db_session):
    await _insert_rule(db_session, bound_user_id=USER_CONSULTANT)
    r = await client.get(OAR, headers=_bearer(), params={"box": "garbage"})
    assert r.status_code == 200
    # box 非法 → 回退 mine（不报错、不泄露 inbox）。
    assert all(it["box"] == "mine" for it in r.json()["items"])

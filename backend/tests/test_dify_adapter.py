"""R4 Dify 网关测试（fake WeKnora + fake LLM，不打网络 / 不接真实 Dify）。

覆盖：
- External Knowledge 官方请求形态 → records；缺/错 Bearer → 拒；缺调用人身份 → fail closed。
- 调用人解析 + 权限强制；A4 agent 渠道不返回原文；L5 非治理不可发现；无权不给原始上下文。
- records.metadata 恒为安全 dict（非 null）。
- HTTP Tool 走 agent 渠道返回 R3 SearchResponse。
- 接入注册管理（admin）：创建一次性返回 token、列表不含 token_hash、PATCH 启停、非 admin 403。
- 无 weknora kb/doc/chunk id / external_* / token_hash / dataset/workflow id / 未脱敏 chunk 泄露。
"""

from __future__ import annotations

import uuid

import pytest

from app.main import app
from app.models.agent_registry import AgentWhitelistRule
from app.seed.dev_seed import (
    KA_COMPANY_L2,
    KA_COMPANY_L4,
    KA_COMPANY_L5,
    KA_PROJECT_ALPHA,
    KA_PROJECT_ALPHA_A4,
    PROJECT_ALPHA,
    PROJECT_BETA,
    USER_ADMIN_ONLY,
    USER_CONSULTANT,
)
from app.services.agent_registry import hash_token
from app.services.llm_client import get_llm_client
from app.services.weknora_client import get_weknora_client

RETRIEVAL = "/api/v1/dify/external-knowledge/retrieval"
TOOL = "/api/v1/dify/tools/knowledge-search"
WHITELIST = "/api/v1/admin/permissions/agent-whitelist"

_ALPHA_KB = f"wk-kb-proj-{PROJECT_ALPHA}"
_COMPANY_KB = "wk-kb-company"
_TOKEN = "kgw_test_dify_token_value"

_SENSITIVE = "原始客户敏感正文：客户XYZ，金额888万元（未脱敏，绝不外发）。"


def _doc(asset_id, kb_id, content):
    return {"knowledge_id": f"wk-doc-{asset_id}", "kb_id": kb_id, "content": content}


class FakeSearchWeKnora:
    def __init__(self, docs):
        self.docs = docs

    async def search(self, *, query, kb_ids, knowledge_ids=None, top_k=20, trace_id=None):
        out = []
        for i, d in enumerate(self.docs):
            if d["kb_id"] not in kb_ids:
                continue
            if knowledge_ids and d["knowledge_id"] not in knowledge_ids:
                continue
            out.append({"content": d["content"], "knowledge_id": d["knowledge_id"],
                        "chunk_index": 0, "score": round(1.0 - i * 0.01, 4), "seq": 0})
        return out

    async def hybrid_search(self, **_):
        return []


class FakeLLM:
    provider = "deepseek"
    model = "deepseek-chat"

    async def chat_completion(self, messages, *, temperature=0.2, model=None, json_object=True, trace_id=None):
        system = messages[0]["content"] if messages else ""
        if "脱敏" in system:
            text = messages[1]["content"] if len(messages) > 1 else ""
            return text.replace("客户XYZ", "【客户】").replace("888万元", "【金额】")
        return "【LLM 答案】综合回答。[1]"


def _install(docs):
    app.dependency_overrides[get_weknora_client] = lambda: FakeSearchWeKnora(docs)
    app.dependency_overrides[get_llm_client] = lambda: FakeLLM()


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.pop(get_weknora_client, None)
    app.dependency_overrides.pop(get_llm_client, None)


async def _insert_rule(db_session, *, token=_TOKEN, enabled=True, capability="qa",
                       max_conf="L5", max_ai="A4", allowed_scope=None, allowed_project_id=None):
    rule = AgentWhitelistRule(
        provider="dify", agent_identifier=f"dify-app-{uuid.uuid4().hex[:8]}",
        agent_name="测试 Dify 接入", capability=capability,
        allowed_scope=allowed_scope, allowed_project_id=allowed_project_id,
        max_confidentiality_level=max_conf, max_ai_access_level=max_ai,
        token_hash=hash_token(token), enabled=enabled,
        external_app_id="dify-secret-app-id", external_workflow_id="dify-secret-wf-id",
    )
    db_session.add(rule)
    await db_session.commit()
    return rule


def _bearer(token=_TOKEN):
    return {"Authorization": f"Bearer {token}"}


_LEAK_TOKENS = [
    "wk-kb", "wk-doc", "weknora", "kb_id", "doc_id", "chunk_id", "chunk_ref",
    "dataset_id", "workflow_id", "external_app_id", "external_workflow_id",
    "api_key", "token_hash", "storage_ref", "dify-secret",
]


def _assert_no_leak(text):
    for t in _LEAK_TOKENS:
        assert t not in text, f"响应不应泄露 {t}"


# ---------------- External Knowledge：鉴权 ----------------
async def test_external_missing_bearer_rejected(client, db_session):
    await _insert_rule(db_session)
    _install([_doc(KA_PROJECT_ALPHA, _ALPHA_KB, "Alpha 内容")])
    resp = await client.post(RETRIEVAL, json={
        "knowledge_id": f"project:{PROJECT_ALPHA}", "query": "q",
        "retrieval_setting": {"top_k": 3, "score_threshold": 0.0},
    })
    assert resp.status_code == 403
    assert resp.json()["error_code"] == 1001


async def test_external_invalid_token_rejected(client, db_session):
    await _insert_rule(db_session)
    _install([_doc(KA_PROJECT_ALPHA, _ALPHA_KB, "Alpha 内容")])
    resp = await client.post(RETRIEVAL, headers=_bearer("wrong-token"), json={
        "knowledge_id": f"project:{PROJECT_ALPHA}", "query": "q",
        "retrieval_setting": {"top_k": 3, "score_threshold": 0.0},
    })
    assert resp.status_code == 403
    assert resp.json()["error_code"] == 1002


async def test_external_disabled_rule_rejected(client, db_session):
    await _insert_rule(db_session, enabled=False)
    _install([_doc(KA_PROJECT_ALPHA, _ALPHA_KB, "Alpha 内容")])
    resp = await client.post(RETRIEVAL, headers=_bearer(), json={
        "knowledge_id": f"project:{PROJECT_ALPHA}", "query": "q",
        "metadata_condition": {"caller_user_id": str(USER_CONSULTANT)},
    })
    assert resp.status_code == 403
    assert resp.json()["error_code"] == 1002


async def test_external_missing_caller_fails_closed(client, db_session):
    await _insert_rule(db_session)
    _install([_doc(KA_PROJECT_ALPHA, _ALPHA_KB, "Alpha 内容")])
    # 合法 token 但无调用人身份 → fail closed（不以 Dify/admin 身份检索）。
    resp = await client.post(RETRIEVAL, headers=_bearer(), json={
        "knowledge_id": f"project:{PROJECT_ALPHA}", "query": "q",
    })
    assert resp.status_code == 403
    assert resp.json()["error_code"] == 1002


# ---------------- External Knowledge：检索 + 权限 ----------------
async def test_external_retrieval_returns_records(client, db_session):
    await _insert_rule(db_session)
    _install([_doc(KA_PROJECT_ALPHA, _ALPHA_KB, "Alpha 供应链优化：采购、仓储、物流要点。")])
    resp = await client.post(RETRIEVAL, headers=_bearer(), json={
        "knowledge_id": f"project:{PROJECT_ALPHA}", "query": "供应链优化",
        "retrieval_setting": {"top_k": 3, "score_threshold": 0.0},
        "metadata_condition": {"caller_user_id": str(USER_CONSULTANT)},
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "records" in body and len(body["records"]) >= 1
    rec = body["records"][0]
    assert rec["content"] and rec["title"]
    assert isinstance(rec["metadata"], dict) and rec["metadata"] != None  # noqa: E711
    assert rec["metadata"]["scope"] == "project"
    assert "asset_id" in rec["metadata"]
    _assert_no_leak(resp.text)


async def test_external_caller_via_header(client, db_session):
    await _insert_rule(db_session)
    _install([_doc(KA_PROJECT_ALPHA, _ALPHA_KB, "Alpha 内容若干")])
    resp = await client.post(
        RETRIEVAL,
        headers={**_bearer(), "X-Platform-User-Id": str(USER_CONSULTANT)},
        json={"knowledge_id": f"project:{PROJECT_ALPHA}", "query": "知识"},
    )
    assert resp.status_code == 200
    assert len(resp.json()["records"]) >= 1


async def test_external_a4_no_original_context(client, db_session):
    await _insert_rule(db_session)
    _install([_doc(KA_PROJECT_ALPHA_A4, _ALPHA_KB, _SENSITIVE)])
    resp = await client.post(RETRIEVAL, headers=_bearer(), json={
        "knowledge_id": f"project:{PROJECT_ALPHA}", "query": "A4 受限交付物",
        "metadata_condition": {"caller_user_id": str(USER_CONSULTANT)},
    })
    assert resp.status_code == 200
    recs = resp.json()["records"]
    for r in recs:
        if r["metadata"].get("asset_id") == str(KA_PROJECT_ALPHA_A4):
            # A4 在 agent 渠道不得以 original 返回，且不外泄未脱敏原文。
            assert r["metadata"]["used_access_layer"] != "original"
    assert "客户XYZ" not in resp.text
    _assert_no_leak(resp.text)


async def test_external_l5_not_discoverable_for_consultant(client, db_session):
    await _insert_rule(db_session)
    _install([
        _doc(KA_COMPANY_L2, _COMPANY_KB, "公司 L2 内容"),
        _doc(KA_COMPANY_L5, _COMPANY_KB, "公司 L5 绝密原文"),
    ])
    resp = await client.post(RETRIEVAL, headers=_bearer(), json={
        "knowledge_id": "company", "query": "战略",
        "metadata_condition": {"caller_user_id": str(USER_CONSULTANT)},
    })
    assert resp.status_code == 200
    ids = {r["metadata"].get("asset_id") for r in resp.json()["records"]}
    assert str(KA_COMPANY_L5) not in ids


async def test_external_non_member_project_no_context(client, db_session):
    await _insert_rule(db_session)
    # consultant 的 Beta 成员关系为 inactive → 非有效成员；请求 Beta 项目 → 无记录。
    _install([_doc(uuid.uuid4(), f"wk-kb-proj-{PROJECT_BETA}", _SENSITIVE)])
    resp = await client.post(RETRIEVAL, headers=_bearer(), json={
        "knowledge_id": f"project:{PROJECT_BETA}", "query": "客户",
        "metadata_condition": {"caller_user_id": str(USER_CONSULTANT)},
    })
    assert resp.status_code == 200
    assert resp.json()["records"] == []
    assert "客户XYZ" not in resp.text


async def test_external_company_l4_summary_not_raw(client, db_session):
    await _insert_rule(db_session)
    # 公司 L4：consultant 无原文权 → record 用脱敏摘要，绝不原始 chunk。
    _install([_doc(KA_COMPANY_L4, _COMPANY_KB, _SENSITIVE)])
    resp = await client.post(RETRIEVAL, headers=_bearer(), json={
        "knowledge_id": "company", "query": "集采",
        "metadata_condition": {"caller_user_id": str(USER_CONSULTANT)},
    })
    assert resp.status_code == 200
    text = resp.text
    assert "客户XYZ" not in text and "888万元" not in text
    for r in resp.json()["records"]:
        if r["metadata"].get("asset_id") == str(KA_COMPANY_L4):
            assert r["metadata"]["used_access_layer"] != "original"


async def test_external_invalid_knowledge_id(client, db_session):
    await _insert_rule(db_session)
    _install([])
    resp = await client.post(RETRIEVAL, headers=_bearer(), json={
        "knowledge_id": "bogus-format", "query": "q",
        "metadata_condition": {"caller_user_id": str(USER_CONSULTANT)},
    })
    assert resp.status_code == 404
    assert resp.json()["error_code"] == 2001


# ---------------- 注册行 scope / project 天花板（R4_FIX）----------------
async def test_external_company_only_token_cannot_get_project(client, db_session):
    await _insert_rule(db_session, allowed_scope="company")
    _install([_doc(KA_PROJECT_ALPHA, _ALPHA_KB, "Alpha 内容（不应被 company-only 接入取到）")])
    resp = await client.post(RETRIEVAL, headers=_bearer(), json={
        "knowledge_id": f"project:{PROJECT_ALPHA}", "query": "供应链",
        "metadata_condition": {"caller_user_id": str(USER_CONSULTANT)},
    })
    assert resp.status_code == 200
    assert resp.json()["records"] == []


async def test_external_company_only_token_allows_company(client, db_session):
    await _insert_rule(db_session, allowed_scope="company")
    _install([_doc(KA_COMPANY_L2, _COMPANY_KB, "公司 L2 内容")])
    resp = await client.post(RETRIEVAL, headers=_bearer(), json={
        "knowledge_id": "company", "query": "成熟度",
        "metadata_condition": {"caller_user_id": str(USER_CONSULTANT)},
    })
    assert resp.status_code == 200
    assert len(resp.json()["records"]) >= 1


async def test_external_project_pinned_token_blocks_other_scopes(client, db_session):
    # 锁定到 Alpha 的接入：仅 project:ALPHA 可取，company / all / 其它项目均空。
    await _insert_rule(db_session, allowed_scope="project", allowed_project_id=PROJECT_ALPHA)
    _install([
        _doc(KA_PROJECT_ALPHA, _ALPHA_KB, "Alpha 内容"),
        _doc(KA_COMPANY_L2, _COMPANY_KB, "公司内容"),
    ])
    mc = {"caller_user_id": str(USER_CONSULTANT)}
    # 其它项目（Beta）→ 空。
    r_beta = await client.post(RETRIEVAL, headers=_bearer(), json={
        "knowledge_id": f"project:{PROJECT_BETA}", "query": "q", "metadata_condition": mc})
    assert r_beta.json()["records"] == []
    # company → 空。
    r_company = await client.post(RETRIEVAL, headers=_bearer(), json={
        "knowledge_id": "company", "query": "q", "metadata_condition": mc})
    assert r_company.json()["records"] == []
    # all → 空。
    r_all = await client.post(RETRIEVAL, headers=_bearer(), json={
        "knowledge_id": "all", "query": "q", "metadata_condition": mc})
    assert r_all.json()["records"] == []
    # 锁定项目本身 → 有记录。
    r_alpha = await client.post(RETRIEVAL, headers=_bearer(), json={
        "knowledge_id": f"project:{PROJECT_ALPHA}", "query": "q", "metadata_condition": mc})
    assert r_alpha.status_code == 200
    assert len(r_alpha.json()["records"]) >= 1


async def test_tool_company_only_token_rejects_project_and_all(client, db_session):
    await _insert_rule(db_session, allowed_scope="company")
    _install([_doc(KA_PROJECT_ALPHA, _ALPHA_KB, "Alpha 内容")])
    # project scope 与 company-only 冲突 → 403。
    r_proj = await client.post(TOOL, headers=_bearer(), json={
        "caller_user_id": str(USER_CONSULTANT), "query": "q", "scope": "project"})
    assert r_proj.status_code == 403
    assert r_proj.json()["detail"]["denied_reason"] == "agent_scope_denied"
    # 缺省 scope（=all）也与 company-only 冲突 → 403（不落回 all）。
    r_all = await client.post(TOOL, headers=_bearer(), json={
        "caller_user_id": str(USER_CONSULTANT), "query": "q"})
    assert r_all.status_code == 403
    # company scope 一致 → 放行。
    r_comp = await client.post(TOOL, headers=_bearer(), json={
        "caller_user_id": str(USER_CONSULTANT), "query": "q", "scope": "company"})
    assert r_comp.status_code == 200


async def test_tool_project_pinned_token_fails_closed(client, db_session):
    await _insert_rule(db_session, allowed_scope="project", allowed_project_id=PROJECT_ALPHA)
    _install([_doc(KA_PROJECT_ALPHA, _ALPHA_KB, "Alpha 内容")])
    # 项目锁定接入经 HTTP Tool 无法安全收口到单一项目 → fail closed 403。
    resp = await client.post(TOOL, headers=_bearer(), json={
        "caller_user_id": str(USER_CONSULTANT), "query": "q", "scope": "project"})
    assert resp.status_code == 403
    assert resp.json()["detail"]["denied_reason"] == "agent_scope_denied"


# ---------------- HTTP Tool ----------------
async def test_tool_search_agent_channel(client, db_session):
    await _insert_rule(db_session)
    _install([_doc(KA_PROJECT_ALPHA, _ALPHA_KB, "Alpha 供应链优化要点。")])
    resp = await client.post(TOOL, headers=_bearer(), json={
        "caller_user_id": str(USER_CONSULTANT), "query": "如何做供应链优化？", "scope": "project",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["intent"] == "qa"
    assert len(body["cards"]) >= 1
    _assert_no_leak(resp.text)


async def test_tool_requires_auth_and_caller(client, db_session):
    await _insert_rule(db_session)
    _install([_doc(KA_PROJECT_ALPHA, _ALPHA_KB, "x")])
    # 缺 token → 401。
    r1 = await client.post(TOOL, json={"caller_user_id": str(USER_CONSULTANT), "query": "q"})
    assert r1.status_code == 401
    # 不存在的 caller → fail closed 403。
    r2 = await client.post(TOOL, headers=_bearer(), json={
        "caller_user_id": str(uuid.uuid4()), "query": "q",
    })
    assert r2.status_code == 403
    assert r2.json()["detail"]["denied_reason"] == "caller_unresolved"


# ---------------- 接入注册管理（admin）----------------
async def test_registry_admin_crud_and_token_once(client):
    # admin 创建 → 一次性返回明文 token；列表不含 token_hash。
    create = await client.post(WHITELIST, headers={"X-Dev-User-Id": str(USER_ADMIN_ONLY)}, json={
        "provider": "dify", "agent_identifier": "dify-app-001", "agent_name": "市场助手",
        "capability": "qa", "max_confidentiality_level": "L2", "max_ai_access_level": "A2",
    })
    assert create.status_code == 200, create.text
    body = create.json()
    assert body["token"] and body["token"].startswith("kgw_")
    rule_id = body["rule"]["id"]
    # 安全视图无 token_hash / external_* / agent_identifier。
    for k in ("token_hash", "external_app_id", "external_workflow_id", "agent_identifier"):
        assert k not in body["rule"]

    lst = await client.get(WHITELIST, headers={"X-Dev-User-Id": str(USER_ADMIN_ONLY)})
    assert lst.status_code == 200
    assert any(r["id"] == rule_id for r in lst.json()["items"])
    _assert_no_leak(lst.text)
    assert "token" not in lst.text

    # PATCH 停用。
    patch = await client.patch(f"{WHITELIST}/{rule_id}", headers={"X-Dev-User-Id": str(USER_ADMIN_ONLY)},
                               json={"enabled": False})
    assert patch.status_code == 200
    assert patch.json()["rule"]["enabled"] is False
    assert patch.json()["token"] is None  # 未重置 token → 不返回明文


async def test_registry_admin_only(client):
    # 非 admin（consultant）→ 403。
    resp = await client.get(WHITELIST, headers={"X-Dev-User-Id": str(USER_CONSULTANT)})
    assert resp.status_code == 403
    assert resp.json()["detail"]["denied_reason"] == "agent_registry_admin_only"

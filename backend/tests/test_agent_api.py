"""Agent / Dify Gateway API 测试（IMPLEMENT-08 最小闭环）。

覆盖：
1. 项目成员 Q&A 成功，返回 call_id / answer / citations。
2. 纯 admin Q&A 403 admin_business_permission_denied。
3. 非项目成员 Q&A 403 project_membership_required。
4. A4 项目资产不以 original 作为 citation 层级。
5. L5 / archived 不进入引用，也不在可见 decision-items 中暴露。
6. decision-items 可查询，returned_layer 与 permission service 口径一致。
7. citation 的 used_access_layer 不超过对应 decision item 的 returned_layer。
8. 调用记录 / decision-items 响应不泄露内部敏感字段。
"""

from __future__ import annotations

import pytest

from app.main import app
from app.seed.dev_seed import (
    KA_PROJECT_ALPHA,
    KA_PROJECT_ALPHA_A4,
    KA_PROJECT_ALPHA_ARCHIVED,
    KA_PROJECT_ALPHA_L5,
    KA_PROJECT_ALPHA_MATERIAL,
    KA_PROJECT_ALPHA_REVIEWABLE,
    PROJECT_ALPHA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
    USER_PROJECT_MANAGER,
)
from app.services.llm_client import get_llm_client
from app.services.weknora_client import get_weknora_client

QA = f"/api/v1/projects/{PROJECT_ALPHA}/qa"

# Alpha 项目 KB（与 seed `_kb_for` 一致）；fake WeKnora 据此把召回 chunk 映射回资产。
_ALPHA_KB = f"wk-kb-proj-{PROJECT_ALPHA}"
# Alpha 项目下所有 seed 资产（含 L5 / archived，用于验证 recall 映射阶段的过滤）。
_ALPHA_ASSETS = [
    KA_PROJECT_ALPHA,
    KA_PROJECT_ALPHA_A4,
    KA_PROJECT_ALPHA_MATERIAL,
    KA_PROJECT_ALPHA_REVIEWABLE,
    KA_PROJECT_ALPHA_L5,
    KA_PROJECT_ALPHA_ARCHIVED,
]


class FakeSearchWeKnora:
    """R3 fake WeKnora：按 kb_ids / knowledge_ids 过滤返回 chunk（不打网络）。"""

    def __init__(self, docs):
        # docs: list of {"knowledge_id","kb_id","content"}
        self.docs = docs

    async def search(self, *, query, kb_ids, knowledge_ids=None, top_k=20, trace_id=None):
        out = []
        for i, d in enumerate(self.docs):
            if d["kb_id"] not in kb_ids:
                continue
            if knowledge_ids and d["knowledge_id"] not in knowledge_ids:
                continue
            out.append({
                "content": d["content"],
                "knowledge_id": d["knowledge_id"],
                "chunk_index": 0,
                "score": round(1.0 - i * 0.01, 4),
                "seq": 0,
                "start": None,
                "end": None,
            })
        return out

    async def hybrid_search(self, **_):
        return []


class FakeAnswerLLM:
    """R3 fake LLM：脱敏请求 → 擦洗敏感实体；问答请求 → 固定答案。"""

    provider = "deepseek"
    model = "deepseek-chat"

    async def chat_completion(self, messages, *, temperature=0.2, model=None, json_object=True, trace_id=None):
        system = messages[0]["content"] if messages else ""
        if "脱敏" in system:
            text = messages[1]["content"] if len(messages) > 1 else ""
            return text.replace("客户敏感实体XYZ", "【客户】").replace("金额888万元", "【金额】")
        return "【LLM 答案】基于本项目知识，供应链优化要点：采购、仓储、物流三方面协同。[1]"


@pytest.fixture(autouse=True)
def _agent_clients():
    """为所有 Agent QA 用例注入 fake WeKnora（召回 Alpha 全部 seed 资产）+ fake LLM。"""
    docs = [
        {"knowledge_id": f"wk-doc-{aid}", "kb_id": _ALPHA_KB,
         "content": "Alpha 项目供应链优化相关知识内容，含采购、仓储、物流要点若干。"}
        for aid in _ALPHA_ASSETS
    ]
    app.dependency_overrides[get_weknora_client] = lambda: FakeSearchWeKnora(docs)
    app.dependency_overrides[get_llm_client] = lambda: FakeAnswerLLM()
    yield
    app.dependency_overrides.pop(get_weknora_client, None)
    app.dependency_overrides.pop(get_llm_client, None)

_LAYER_RANK = {"discovery": 1, "summary": 2, "original": 3}

_LEAK_TOKENS = [
    "storage_ref",
    "source_file_ref",
    "vector_id",
    "api_key",
    "dataset_id",
    "workflow_id",
    "kb_id",
    "bucket",
    "s3://",
    "oss://",
    "download_url",
    "file_url",
    "preview_token",
]


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


def _assert_no_leak(text: str):
    for t in _LEAK_TOKENS:
        assert t not in text, f"响应不应泄露 {t}"


async def test_project_member_qa_success(client):
    """项目成员 Q&A 成功，返回 call_id、回答、引用；引用都来自 Alpha active 资产。"""
    resp = await client.post(
        QA, headers=_hdr(USER_CONSULTANT), json={"query": "Alpha 项目供应链优化有哪些要点？"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["call_id"]
    assert body["response_text"]
    assert body["decision_status"] == "allowed"
    assert body["model_key"] == "system_default"
    assert len(body["citations"]) >= 1
    # 每条引用都有标题、scope=project、合法层级；契约字段为 cited_zone。
    for c in body["citations"]:
        assert c["asset_title"]
        assert c["scope"] == "project"
        assert c["used_access_layer"] in _LAYER_RANK
        assert c["cited_zone"] in ("material", "asset")
        assert "zone" not in c  # 旧字段名已下线，对齐契约
    _assert_no_leak(resp.text)


async def test_admin_qa_403(client):
    """纯 admin 发起 Q&A → 403 admin_business_permission_denied。"""
    resp = await client.post(QA, headers=_hdr(USER_ADMIN_ONLY), json={"query": "x"})
    assert resp.status_code == 403
    assert resp.json()["detail"]["denied_reason"] == "admin_business_permission_denied"


async def test_non_member_qa_403(client):
    """非项目成员（咨询总监，无 Alpha 成员关系）→ 403 project_membership_required。"""
    resp = await client.post(QA, headers=_hdr(USER_DIRECTOR), json={"query": "x"})
    assert resp.status_code == 403
    assert resp.json()["detail"]["denied_reason"] == "project_membership_required"


async def test_a4_not_cited_as_original(client):
    """A4 项目资产在 Agent 渠道不以 original 作为引用层级（最多 summary）。"""
    resp = await client.post(
        QA, headers=_hdr(USER_CONSULTANT), json={"query": "A4 受限交付物相关内容"}
    )
    assert resp.status_code == 200
    call_id = resp.json()["call_id"]
    # 检查 decision-items 中 A4 资产 original_allowed=False、returned_layer<=summary。
    items = (
        await client.get(
            f"/api/v1/agent-calls/{call_id}/decision-items", headers=_hdr(USER_CONSULTANT)
        )
    ).json()["items"]
    a4 = next(i for i in items if i["target_asset_id"] == str(KA_PROJECT_ALPHA_A4))
    assert a4["original_allowed"] is False
    assert a4["returned_layer"] in ("summary", "discovery")
    # 若 A4 出现在引用中，层级必须不是 original。
    for c in resp.json()["citations"]:
        if c["asset_id"] == str(KA_PROJECT_ALPHA_A4):
            assert c["used_access_layer"] != "original"


async def test_l5_and_archived_not_cited(client):
    """L5（不可发现）与 archived（非 active）不进入引用与可见 decision-items。"""
    resp = await client.post(
        QA, headers=_hdr(USER_CONSULTANT), json={"query": "项目知识"}
    )
    call_id = resp.json()["call_id"]
    cited_ids = {c["asset_id"] for c in resp.json()["citations"]}
    assert str(KA_PROJECT_ALPHA_L5) not in cited_ids
    assert str(KA_PROJECT_ALPHA_ARCHIVED) not in cited_ids

    items = (
        await client.get(
            f"/api/v1/agent-calls/{call_id}/decision-items", headers=_hdr(USER_CONSULTANT)
        )
    ).json()["items"]
    item_ids = {i["target_asset_id"] for i in items}
    # L5 不在可见 decision-items（避免存在性泄露）；archived 不进候选。
    assert str(KA_PROJECT_ALPHA_L5) not in item_ids
    assert str(KA_PROJECT_ALPHA_ARCHIVED) not in item_ids


async def test_decision_items_returned_layer_matches_permission(client):
    """decision-items 可查询；普通 L2 项目资产对成员可达 original，A4 仅到 summary。"""
    resp = await client.post(
        QA, headers=_hdr(USER_CONSULTANT), json={"query": "供应链优化"}
    )
    call_id = resp.json()["call_id"]
    items = (
        await client.get(
            f"/api/v1/agent-calls/{call_id}/decision-items", headers=_hdr(USER_CONSULTANT)
        )
    ).json()["items"]
    by_id = {i["target_asset_id"]: i for i in items}
    # Alpha L2 asset：项目成员 → 三层全开，returned_layer=original。
    l2 = by_id[str(KA_PROJECT_ALPHA)]
    assert l2["returned_layer"] == "original"
    assert l2["effective_access_source"] == "project_member"
    # A4：original 被 Agent 渠道降级，returned_layer=summary。
    a4 = by_id[str(KA_PROJECT_ALPHA_A4)]
    assert a4["returned_layer"] == "summary"


async def test_citation_layer_not_exceed_returned_layer(client):
    """每条 citation 的 used_access_layer 不超过对应 decision item 的 returned_layer。"""
    resp = await client.post(
        QA, headers=_hdr(USER_CONSULTANT), json={"query": "项目交付与方法论"}
    )
    call_id = resp.json()["call_id"]
    citations = resp.json()["citations"]
    items = (
        await client.get(
            f"/api/v1/agent-calls/{call_id}/decision-items", headers=_hdr(USER_CONSULTANT)
        )
    ).json()["items"]
    returned_by_asset = {i["target_asset_id"]: i["returned_layer"] for i in items}
    for c in citations:
        returned = returned_by_asset[c["asset_id"]]
        assert returned is not None
        assert _LAYER_RANK[c["used_access_layer"]] <= _LAYER_RANK[returned]


async def test_agent_call_visibility_and_no_leak(client):
    """调用记录可见性：本人/boss 可见，纯 admin 403，他人业务用户 404；响应不泄露内部字段。"""
    call_id = (
        await client.post(
            QA, headers=_hdr(USER_CONSULTANT), json={"query": "项目知识问答"}
        )
    ).json()["call_id"]
    url = f"/api/v1/agent-calls/{call_id}"

    # 本人可见。
    own = await client.get(url, headers=_hdr(USER_CONSULTANT))
    assert own.status_code == 200
    body = own.json()
    assert body["call_id"] == call_id
    # 契约 §15：query_text + 人类可读名（非空）。
    assert body["query_text"] == "项目知识问答"
    assert body["caller_name"]
    assert body["project_name"]
    _assert_no_leak(own.text)
    # provider 为平台抽象标识（R3 真实链路），不暴露 Dify 内部标识。
    assert body["provider"] == "weknora_llm"

    # boss（治理角色）可见。
    assert (await client.get(url, headers=_hdr(USER_BOSS))).status_code == 200

    # 纯 admin → 403 admin_business_permission_denied。
    admin = await client.get(url, headers=_hdr(USER_ADMIN_ONLY))
    assert admin.status_code == 403
    assert admin.json()["detail"]["denied_reason"] == "admin_business_permission_denied"

    # 他人业务用户（经理B，非调用人、非治理）→ 404，不泄露调用存在。
    other = await client.get(url, headers=_hdr(USER_PROJECT_MANAGER))
    assert other.status_code == 404


async def test_decision_items_no_leak(client):
    """decision-items 响应不泄露内部敏感字段。"""
    call_id = (
        await client.post(QA, headers=_hdr(USER_CONSULTANT), json={"query": "项目知识"})
    ).json()["call_id"]
    resp = await client.get(
        f"/api/v1/agent-calls/{call_id}/decision-items", headers=_hdr(USER_CONSULTANT)
    )
    assert resp.status_code == 200
    _assert_no_leak(resp.text)

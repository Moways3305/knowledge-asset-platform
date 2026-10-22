"""Agent Gateway API 测试（IMPLEMENT-08 最小闭环）。

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

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.main import app
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetSummary, KnowledgeAssetVersion
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
from app.services import generation_models, retrieval
from app.services.llm_client import LLMClient, LLMError, get_llm_client
from app.services.weknora_client import get_weknora_client

QA = f"/api/v1/projects/{PROJECT_ALPHA}/qa"
QA_MODELS = f"{QA}/model-options"

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
    """fake WeKnora：按 kb_ids / knowledge_ids 过滤返回 chunk（不打网络）。"""

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
            out.append(
                {
                    "content": d["content"],
                    "knowledge_id": d["knowledge_id"],
                    "chunk_index": 0,
                    "score": round(1.0 - i * 0.01, 4),
                    "seq": 0,
                    "start": None,
                    "end": None,
                }
            )
        return out

    async def hybrid_search(self, **_):
        return []


class FakeAnswerLLM:
    """fake LLM：脱敏请求 → 擦洗敏感实体；问答请求 → 固定答案。"""

    provider = "deepseek"
    model = "deepseek-chat"

    async def chat_completion(
        self,
        messages,
        *,
        temperature=0.2,
        model=None,
        json_object=True,
        trace_id=None,
        max_tokens=None,
    ):
        system = messages[0]["content"] if messages else ""
        if "脱敏" in system:
            text = messages[1]["content"] if len(messages) > 1 else ""
            return text.replace("客户敏感实体XYZ", "【客户】").replace("金额888万元", "【金额】")
        if max_tokens == 250:
            return json.dumps({"queries": []})
        evidence = json.loads(messages[1]["content"])["evidence"]
        return json.dumps(
            {
                "status": "answered",
                "answer_parts": [
                    {
                        "text": "【LLM 答案】基于本项目知识，供应链优化要点：采购、仓储、物流三方面协同。",
                        "citation_orders": [item["order"] for item in evidence],
                    }
                ],
            }
        )


@pytest.fixture(autouse=True)
def _agent_clients():
    """为所有 Agent QA 用例注入 fake WeKnora（召回 Alpha 全部 seed 资产）+ fake LLM。"""
    docs = [
        {
            "knowledge_id": f"wk-doc-{aid}",
            "kb_id": _ALPHA_KB,
            "content": "Alpha 项目供应链优化相关知识内容，含采购、仓储、物流要点若干。",
        }
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


class StructuredProjectAnswer(FakeAnswerLLM):
    def __init__(self, response: str):
        self.response = response

    async def chat_completion(self, messages, **kwargs):
        if messages and "脱敏" in messages[0]["content"]:
            return await super().chat_completion(messages, **kwargs)
        return self.response


async def test_project_refusal_has_no_unrelated_citations(client):
    llm = StructuredProjectAnswer(json.dumps({"status": "insufficient_evidence"}))
    app.dependency_overrides[get_llm_client] = lambda: llm
    response = await client.post(QA, headers=_hdr(USER_CONSULTANT), json={"query": "测试事实"})
    assert response.status_code == 200, response.text
    assert response.json()["citations"] == []
    assert response.json()["answer_status"] == "insufficient_evidence"
    history = await client.get(
        f"/api/v1/agent-calls/{response.json()['call_id']}", headers=_hdr(USER_CONSULTANT)
    )
    assert history.status_code == 200
    assert history.json()["citations"] == []


async def test_project_answer_only_persists_actually_cited_evidence(client):
    llm = StructuredProjectAnswer(
        json.dumps(
            {"status": "answered", "answer_parts": [{"text": "测试结论", "citation_orders": [2]}]}
        )
    )
    app.dependency_overrides[get_llm_client] = lambda: llm
    response = await client.post(QA, headers=_hdr(USER_CONSULTANT), json={"query": "测试事实"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["response_text"] == "测试结论[2]"
    assert [citation["citation_order"] for citation in body["citations"]] == [2]
    history = await client.get(
        f"/api/v1/agent-calls/{body['call_id']}", headers=_hdr(USER_CONSULTANT)
    )
    assert history.status_code == 200, history.text
    assert [citation["citation_order"] for citation in history.json()["citations"]] == [2]


async def test_project_answer_rejects_unstructured_model_response(client):
    llm = StructuredProjectAnswer("未校验的自由文本[999]")
    app.dependency_overrides[get_llm_client] = lambda: llm
    response = await client.post(QA, headers=_hdr(USER_CONSULTANT), json={"query": "测试事实"})
    assert response.status_code == 503, response.text


async def test_project_answer_rejects_out_of_range_structured_citation(client):
    llm = StructuredProjectAnswer(
        json.dumps(
            {"status": "answered", "answer_parts": [{"text": "虚构结论", "citation_orders": [999]}]}
        )
    )
    app.dependency_overrides[get_llm_client] = lambda: llm
    response = await client.post(QA, headers=_hdr(USER_CONSULTANT), json={"query": "测试事实"})
    assert response.status_code == 503, response.text
    assert "虚构结论" not in response.text


async def test_project_planned_title_recalls_known_fact_without_upstream_chunk(client, db_session):
    title = "验收-虚构流程核对"
    asset = await db_session.get(KnowledgeAsset, KA_PROJECT_ALPHA)
    asset.title = title
    version = await db_session.scalar(
        select(KnowledgeAssetVersion).where(
            KnowledgeAssetVersion.asset_id == asset.id,
            KnowledgeAssetVersion.version_status == "active",
        )
    )
    db_session.add(
        KnowledgeAssetSummary(
            asset_id=asset.id,
            version_id=version.id,
            summary_type="redacted_summary",
            content="本虚构验收资料的目录核对码是紫色山川。",
        )
    )
    await db_session.commit()

    class KnownFactAnswer(FakeAnswerLLM):
        async def chat_completion(self, messages, **kwargs):
            if kwargs.get("max_tokens") == 250:
                # The optional model need not infer a named source: preserve
                # the user's literal title even when planning yields nothing.
                return json.dumps({"queries": []})
            if "answer_parts" in messages[0]["content"]:
                evidence = json.loads(messages[1]["content"])["evidence"]
                matching = [
                    e for e in evidence if e["title"] == title and "紫色山川" in e["content"]
                ]
                if not matching:
                    return json.dumps({"status": "insufficient_evidence"})
                return json.dumps(
                    {
                        "status": "answered",
                        "answer_parts": [
                            {
                                "text": "目录核对码是紫色山川。",
                                "citation_orders": [matching[0]["order"]],
                            }
                        ],
                    }
                )
            return await super().chat_completion(messages, **kwargs)

    app.dependency_overrides[get_llm_client] = lambda: KnownFactAnswer()
    app.dependency_overrides[get_weknora_client] = lambda: FakeSearchWeKnora([])
    response = await client.post(
        QA, headers=_hdr(USER_CONSULTANT), json={"query": f"《{title}》中的目录核对码是什么？"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["answer_status"] == "answered"
    assert response.json()["response_text"] == "目录核对码是紫色山川。[1]"
    assert [c["asset_id"] for c in response.json()["citations"]] == [str(KA_PROJECT_ALPHA)]


async def test_project_planning_preserves_original_and_project_kb(client):
    calls = []

    class PlannedAnswer(FakeAnswerLLM):
        async def chat_completion(self, messages, **kwargs):
            if kwargs.get("max_tokens") == 250:
                return json.dumps({"queries": ["供应链优化", "采购协同"]})
            return await super().chat_completion(messages, **kwargs)

    class RecordingSearch(FakeSearchWeKnora):
        async def search(self, **kwargs):
            calls.append(kwargs)
            return await super().search(**kwargs)

    app.dependency_overrides[get_llm_client] = lambda: PlannedAnswer()
    app.dependency_overrides[get_weknora_client] = lambda: RecordingSearch(
        [
            {
                "knowledge_id": f"wk-doc-{KA_PROJECT_ALPHA}",
                "kb_id": _ALPHA_KB,
                "content": "采购协同事实",
            }
        ]
    )
    response = await client.post(
        QA, headers=_hdr(USER_CONSULTANT), json={"query": "怎么一起买东西"}
    )
    assert response.status_code == 200, response.text
    assert {call["query"] for call in calls} == {"怎么一起买东西", "供应链优化", "采购协同"}
    assert all(call["kb_ids"] == [_ALPHA_KB] for call in calls)


async def test_project_scope_guard_excludes_misrouted_candidates(client, monkeypatch):
    recall = retrieval.recall_assets

    async def misrouted(*args, **kwargs):
        candidates = await recall(*args, **kwargs)
        return candidates + [
            SimpleNamespace(asset=SimpleNamespace(scope="company", project_id=PROJECT_ALPHA)),
            SimpleNamespace(asset=SimpleNamespace(scope="project", project_id=USER_BOSS)),
        ]

    monkeypatch.setattr(retrieval, "recall_assets", misrouted)
    response = await client.post(QA, headers=_hdr(USER_CONSULTANT), json={"query": "项目知识"})
    assert response.status_code == 200, response.text
    assert all(c["scope"] == "project" for c in response.json()["citations"])


async def test_project_answer_receives_platform_lifecycle_state(client):
    class StateAnswer(FakeAnswerLLM):
        async def chat_completion(self, messages, **kwargs):
            if "answer_parts" in messages[0]["content"]:
                evidence = json.loads(messages[1]["content"])["evidence"]
                assert evidence
                assert all(
                    e["platform_state"]["version_selection"] in {"current", "legacy_active"}
                    for e in evidence
                )
                assert all("review_status" in e["platform_state"] for e in evidence)
            return await super().chat_completion(messages, **kwargs)

    app.dependency_overrides[get_llm_client] = lambda: StateAnswer()
    response = await client.post(QA, headers=_hdr(USER_CONSULTANT), json={"query": "项目知识"})
    assert response.status_code == 200, response.text


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


async def test_project_qa_model_options_require_membership_and_hide_connection_secrets(
    client, db_session
):
    created = await generation_models.create_model(
        db_session,
        display_name="项目问答连接",
        provider="openai_compatible",
        model_name="qa-model",
        base_url="https://qa.example.test/v1",
        api_key="SECRET-LIKE-project-qa-key",
        enabled=True,
        make_default=False,
        actor_id=USER_ADMIN_ONLY,
    )
    await db_session.commit()

    response = await client.get(QA_MODELS, headers=_hdr(USER_CONSULTANT))
    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "model_ref": created["model_ref"],
            "display_name": "项目问答连接",
            "is_default": False,
        }
    ]
    for forbidden in ("SECRET-LIKE", "qa.example.test", "api_key", "base_url", "model_name"):
        assert forbidden not in response.text

    denied = await client.get(QA_MODELS, headers=_hdr(USER_DIRECTOR))
    assert denied.status_code == 403
    assert denied.json()["detail"]["denied_reason"] == "project_membership_required"


async def test_project_qa_rejects_fake_and_legacy_model_keys(client):
    fake = await client.post(
        QA,
        headers=_hdr(USER_CONSULTANT),
        json={"query": "项目知识", "model_ref": "deepseek-r1"},
    )
    assert fake.status_code == 422
    assert fake.json()["detail"]["denied_reason"] == "project_qa_model_not_found"
    assert "deepseek-r1" not in fake.text

    legacy = await client.post(
        QA,
        headers=_hdr(USER_CONSULTANT),
        json={"query": "项目知识", "model_key": "system_default"},
    )
    assert legacy.status_code == 422


async def test_project_qa_rejects_disabled_model_ref(client, db_session):
    created = await generation_models.create_model(
        db_session,
        display_name="即将停用的问答连接",
        provider="openai_compatible",
        model_name="qa-model",
        base_url="https://qa.example.test/v1",
        api_key="SECRET-LIKE-disabled-key",
        enabled=True,
        make_default=False,
        actor_id=USER_ADMIN_ONLY,
    )
    model = await generation_models.resolve_connection_ref(db_session, created["model_ref"])
    assert model is not None
    model.enabled = False
    await db_session.commit()

    response = await client.post(
        QA,
        headers=_hdr(USER_CONSULTANT),
        json={"query": "项目知识", "model_ref": created["model_ref"]},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["denied_reason"] == "project_qa_model_disabled"
    assert "SECRET-LIKE" not in response.text


async def test_project_qa_rejects_non_chat_model_ref(client, db_session):
    created = await generation_models.create_model(
        db_session,
        display_name="嵌入连接",
        provider="openai_compatible",
        model_name="embedding-model",
        base_url="https://embedding.example.test/v1",
        api_key="SECRET-LIKE-embedding-key",
        enabled=True,
        make_default=False,
        actor_id=USER_ADMIN_ONLY,
        capability_type="embedding",
    )
    await db_session.commit()

    response = await client.post(
        QA,
        headers=_hdr(USER_CONSULTANT),
        json={"query": "项目知识", "model_ref": created["model_ref"]},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["denied_reason"] == "project_qa_model_type_mismatch"
    assert "SECRET-LIKE" not in response.text


async def test_project_qa_uses_external_model_ref_without_weknora_model_bridge(
    client, db_session, monkeypatch
):
    created = await generation_models.create_model(
        db_session,
        display_name="项目问答外部连接",
        provider="openai_compatible",
        model_name="project-qa-chat",
        base_url="https://qa.example.test/v1",
        api_key="SECRET-LIKE-project-qa-external",
        enabled=True,
        make_default=False,
        actor_id=USER_ADMIN_ONLY,
    )
    await db_session.commit()

    async def fake_chat(self, messages, **kwargs):
        system = messages[0]["content"] if messages else ""
        if "脱敏" in system:
            return "【客户】项目供应链优化知识。"
        if kwargs.get("max_tokens") == 250:
            return json.dumps({"queries": []})
        return json.dumps(
            {
                "status": "answered",
                "answer_parts": [
                    {"text": "外部 LLM 基于项目知识生成的回答。", "citation_orders": [1]}
                ],
            }
        )

    monkeypatch.setattr(LLMClient, "chat_completion", fake_chat)
    response = await client.post(
        QA,
        headers=_hdr(USER_CONSULTANT),
        json={"query": "项目知识", "model_ref": created["model_ref"]},
    )
    assert response.status_code == 200
    assert response.json()["model_key"] == created["model_ref"]
    assert response.json()["response_text"].startswith("外部 LLM")
    assert "SECRET-LIKE" not in response.text


async def test_external_llm_failure_does_not_fabricate_project_qa_success(
    client, db_session, monkeypatch
):
    created = await generation_models.create_model(
        db_session,
        display_name="不可用的项目问答连接",
        provider="openai_compatible",
        model_name="unavailable-chat",
        base_url="https://qa.example.test/v1",
        api_key="SECRET-LIKE-unavailable",
        enabled=True,
        make_default=False,
        actor_id=USER_ADMIN_ONLY,
    )
    await db_session.commit()

    async def fail_chat(self, messages, **kwargs):
        raise LLMError("external_llm_unavailable", "SECRET-LIKE upstream body")

    monkeypatch.setattr(LLMClient, "chat_completion", fail_chat)
    response = await client.post(
        QA,
        headers=_hdr(USER_CONSULTANT),
        json={"query": "项目知识", "model_ref": created["model_ref"]},
    )
    assert response.status_code != 200
    assert "SECRET-LIKE" not in response.text
    assert "外部 LLM 基于项目知识生成的回答" not in response.text


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


async def test_own_project_l5_is_citable_but_archived_is_not(client):
    """active 成员可使用本项目 L5；archived 仍不进入引用或 decision-items。"""
    resp = await client.post(QA, headers=_hdr(USER_CONSULTANT), json={"query": "项目知识"})
    call_id = resp.json()["call_id"]
    cited_ids = {c["asset_id"] for c in resp.json()["citations"]}
    assert str(KA_PROJECT_ALPHA_ARCHIVED) not in cited_ids

    items = (
        await client.get(
            f"/api/v1/agent-calls/{call_id}/decision-items", headers=_hdr(USER_CONSULTANT)
        )
    ).json()["items"]
    item_ids = {i["target_asset_id"] for i in items}
    # L5 是可达候选；是否进入有限条数的引用由相关度/证据上限决定。
    assert str(KA_PROJECT_ALPHA_L5) in item_ids
    assert str(KA_PROJECT_ALPHA_ARCHIVED) not in item_ids


async def test_decision_items_returned_layer_matches_permission(client):
    """decision-items 可查询；普通 L2 项目资产对成员可达 original，A4 仅到 summary。"""
    resp = await client.post(QA, headers=_hdr(USER_CONSULTANT), json={"query": "供应链优化"})
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
    resp = await client.post(QA, headers=_hdr(USER_CONSULTANT), json={"query": "项目交付与方法论"})
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
        await client.post(QA, headers=_hdr(USER_CONSULTANT), json={"query": "项目知识问答"})
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
    # provider 为平台抽象标识（真实链路），不暴露 provider 内部标识。
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

"""两阶段检索 / 问答测试（fake WeKnoraClient + fake LLMClient，不打网络）。

覆盖：
- WeKnoraClient.search/hybrid_search 响应规整（单测）。
- 阶段1卡片：query→召回→映射→decide→卡片；L3/L4 摘要脱敏；L5/他人个人不出现；score 排序。
- 阶段2原文：有权→脱敏原文；无权→卡片+联系人、**断言无任何原文 chunk**。
- 输出脱敏：L3/L4 返回内容无客户敏感实体；LLM 不可用→不返回原文（保守降级）。
- 问答：真实检索 + LLM 答案 + 引用只来自放行 chunk。
- 意图识别 6 类 + 降级默认。
- 安全：响应无 kb/doc/chunk id / api_key / 未脱敏 chunk。
- 孤儿 knowledge（无映射）被丢弃。
"""

from __future__ import annotations

import asyncio
import json
import uuid

import httpx
import pytest

from app.main import app
from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetSummary,
    KnowledgeAssetTag,
    KnowledgeAssetVersion,
)
from app.seed.dev_seed import (
    KA_COMPANY_L2,
    KA_COMPANY_L4,
    KA_COMPANY_L5,
    KA_PROJECT_ALPHA,
    KA_PROJECT_BETA_L3,
    PROJECT_ALPHA,
    PROJECT_BETA,
    USER_CONSULTANT,
    USER_DIRECTOR,
)
from app.services.intent import SearchIntent, classify_intent, wants_answer
from app.services.llm_client import get_llm_client
from app.services.weknora_client import WeKnoraClient, get_weknora_client

SEARCH = "/api/v1/knowledge/search"
_ALPHA_KB = f"wk-kb-proj-{PROJECT_ALPHA}"
_BETA_KB = f"wk-kb-proj-{PROJECT_BETA}"
_COMPANY_KB = "wk-kb-company"

# 含客户敏感实体的原文 chunk（用于断言输出脱敏确实擦洗）。
_SENSITIVE = "项目交付涉及客户敏感实体XYZ，合同金额888万元，需脱敏后方可外发。"

# 测试态 L4 Alpha 资产（Alpha 成员可得原文 → 触发输出脱敏）。
KA_ALPHA_L4 = uuid.UUID("00000000-0000-0000-0000-0000000000eb")
# 孤儿 knowledge（fake 返回但业务库无映射）。
_ORPHAN_DOC = "wk-doc-orphan-nomap"


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


def _doc(asset_id, kb_id, content):
    return {"knowledge_id": f"wk-doc-{asset_id}", "kb_id": kb_id, "content": content}


class FakeSearchWeKnora:
    """按 kb_ids / knowledge_ids 过滤返回 chunk。"""

    def __init__(self, docs):
        self.docs = docs
        self.last_knowledge_ids = None

    async def search(self, *, query, kb_ids, knowledge_ids=None, top_k=20, trace_id=None):
        self.last_knowledge_ids = knowledge_ids
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
                }
            )
        return out

    async def hybrid_search(self, **_):
        return []


async def test_directory_filter_constrains_candidates_before_top_k(client, db_session):
    for asset_id in (KA_COMPANY_L4, KA_COMPANY_L5):
        asset = await db_session.get(KnowledgeAsset, asset_id)
        version = await db_session.get(KnowledgeAssetVersion, asset.current_version_id)
        version.directory_key = "company.key_materials"
    await db_session.commit()
    fake = FakeSearchWeKnora(
        [
            _doc(KA_COMPANY_L4, _COMPANY_KB, "globally stronger"),
            _doc(KA_COMPANY_L2, _COMPANY_KB, "methodology result"),
        ]
    )
    app.dependency_overrides[get_weknora_client] = lambda: fake
    response = await client.post(
        SEARCH,
        headers=_hdr(USER_CONSULTANT),
        json={
            "query": "methodology",
            "scope": "company",
            "filters": {"directory_key": "company.methodology"},
        },
    )
    assert response.status_code == 200
    assert fake.last_knowledge_ids == [f"wk-doc-{KA_COMPANY_L2}"]
    assert [item["asset_id"] for item in response.json()["cards"]] == [str(KA_COMPANY_L2)]


class FakeScrubLLM:
    """脱敏请求 → 擦洗敏感实体；问答请求 → 固定答案。"""

    provider = "deepseek"
    model = "deepseek-chat"

    async def chat_completion(
        self, messages, *, temperature=0.2, model=None, json_object=True, trace_id=None
    ):
        system = messages[0]["content"] if messages else ""
        if "脱敏" in system:
            text = messages[1]["content"] if len(messages) > 1 else ""
            return text.replace("客户敏感实体XYZ", "【客户】").replace("888万元", "【金额】")
        return json.dumps(
            {
                "status": "answered",
                "answer": "【LLM 答案】供应链优化要点：采购、仓储、物流协同。[1]",
                "citation_orders": [1],
            }
        )


class DownLLM:
    """LLM 不可用：任何调用抛错（验证保守降级=不返回原文）。"""

    provider = ""
    model = ""

    async def chat_completion(self, *_, **__):
        from app.services.llm_client import LLMError

        raise LLMError("llm_not_configured", "LLM 未配置")


class NoOpScrubLLM:
    """脱敏 no-op：把原文原样返回（模拟 LLM 未真正脱敏）。验证 fail-closed。"""

    provider = "deepseek"
    model = "deepseek-chat"

    async def chat_completion(
        self, messages, *, temperature=0.2, model=None, json_object=True, trace_id=None
    ):
        # 脱敏请求：原样回传用户内容（脱敏未生效）。
        return messages[1]["content"] if len(messages) > 1 else ""


def _install(weknora, llm):
    app.dependency_overrides[get_weknora_client] = lambda: weknora
    app.dependency_overrides[get_llm_client] = lambda: llm


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.pop(get_weknora_client, None)
    app.dependency_overrides.pop(get_llm_client, None)


async def _insert_alpha_l4(db_session):
    """插入一个 L4 Alpha 资产（含原文 chunk 经 fake 返回），Alpha 成员可得原文。"""
    asset = KnowledgeAsset(
        id=KA_ALPHA_L4,
        title="Alpha L4 交付物（含敏感实体）",
        scope="project",
        zone="asset",
        asset_type="deliverable",
        owner_user_id=USER_CONSULTANT,
        maintainer_user_id=USER_CONSULTANT,
        project_id=PROJECT_ALPHA,
        visibility="project_only",
        confidentiality_level="L4",
        ai_access_level="A1",
        asset_status="active",
        lifecycle_phase_key="交付",
    )
    version = KnowledgeAssetVersion(
        asset_id=KA_ALPHA_L4,
        version_no="v1",
        version_status="active",
        created_by=USER_CONSULTANT,
        weknora_kb_id=_ALPHA_KB,
        weknora_doc_id=f"wk-doc-{KA_ALPHA_L4}",
        weknora_parse_status="completed",
        # 该 fixture 表示一个已成功索引的资产（召回/原文取件只接受 indexed）。
        index_status="indexed",
    )
    asset.versions.append(version)
    asset.current_version_id = version.id
    s = KnowledgeAssetSummary(
        summary_type="redacted_summary", content="（脱敏）Alpha L4 交付物安全摘要。"
    )
    s.version = version
    asset.summaries.append(s)
    asset.tags.append(KnowledgeAssetTag(tag_name="交付物"))
    db_session.add(asset)
    await db_session.commit()


_LEAK_TOKENS = ["wk-kb", "wk-doc", "kb_id", "doc_id", "chunk_id", "api_key", "sk-", "storage_ref"]


def _assert_no_leak(text):
    for t in _LEAK_TOKENS:
        assert t not in text, f"响应不应泄露 {t}"


# ---------------- WeKnoraClient 规整单测 ----------------
def test_normalize_chunks_list_and_wrapped():
    direct = WeKnoraClient._normalize_chunks(
        [{"content": "c", "knowledge_id": "d1", "chunk_index": 2, "score": 0.7}]
    )
    assert direct[0]["knowledge_id"] == "d1" and direct[0]["score"] == 0.7
    wrapped = WeKnoraClient._normalize_chunks(
        {"results": [{"text": "c", "doc_id": "d2", "relevance_score": 0.5}]}
    )
    assert wrapped[0]["knowledge_id"] == "d2" and wrapped[0]["content"] == "c"
    # 无 knowledge_id 的项被丢弃。
    assert WeKnoraClient._normalize_chunks([{"content": "x"}]) == []


def test_search_unwrap_payload_shape():
    ok = httpx.Response(
        200,
        json={
            "success": True,
            "data": {
                "results": [
                    {"content": "c", "knowledge_id": "d1", "score": 0.9},
                ]
            },
        },
    )
    chunks = WeKnoraClient._normalize_chunks(WeKnoraClient._unwrap(ok))
    assert chunks[0]["knowledge_id"] == "d1"


# ---------------- 意图识别 ----------------
def test_intent_classification_six_classes_and_default():
    assert classify_intent("帮我总结一下供应链要点") == SearchIntent.summarize
    assert classify_intent("起草一份交付方案") == SearchIntent.generate
    assert classify_intent("检查这份合同是否符合规范") == SearchIntent.check
    assert classify_intent("有没有类似的项目案例") == SearchIntent.recommend
    assert classify_intent("如何做供应链优化？") == SearchIntent.qa
    # 都不命中 → 降级默认 search。
    assert classify_intent("供应链优化交付报告") == SearchIntent.search
    # 显式 intent 覆盖；非法显式 → 走规则。
    assert classify_intent("供应链", explicit="qa") == SearchIntent.qa
    assert classify_intent("供应链", explicit="bogus") == SearchIntent.search
    assert wants_answer(SearchIntent.qa) and not wants_answer(SearchIntent.search)


# ---------------- 阶段1卡片 ----------------
async def test_stage1_cards_company_scope_l4_redacted_l5_hidden(client, db_session):
    docs = [
        _doc(KA_COMPANY_L2, _COMPANY_KB, "零售数字化成熟度评估内容"),
        _doc(KA_COMPANY_L4, _COMPANY_KB, "医药集采渠道影响（内部原文）"),
        _doc(KA_COMPANY_L5, _COMPANY_KB, "公司级绝密战略备忘原文"),
    ]
    _install(FakeSearchWeKnora(docs), FakeScrubLLM())
    resp = await client.post(
        SEARCH, headers=_hdr(USER_CONSULTANT), json={"query": "数字化成熟度", "scope": "company"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    cards = {c["asset_id"]: c for c in body["cards"]}
    # L5 对普通 consultant 不可发现 → 连卡片都没有。
    assert str(KA_COMPANY_L5) not in cards
    # 历史 L2 无脱敏版本时不得回退到普通摘要。
    l2 = cards[str(KA_COMPANY_L2)]
    assert l2["one_liner"] is None
    assert l2["detailed"] is None
    assert l2["key_points"] == []
    assert l2["can_view_original"] is False
    # L4 卡片：detailed 取脱敏摘要、key_points 置空、不可得原文。
    l4 = cards[str(KA_COMPANY_L4)]
    assert "脱敏" in (l4["detailed"] or "")
    assert l4["key_points"] == []
    assert l4["can_view_original"] is False
    _assert_no_leak(resp.text)

    from app.services.authorized_summary_backfill import backfill_authorized_summaries

    await backfill_authorized_summaries(db_session, dry_run=False)
    refreshed = await client.post(
        SEARCH, headers=_hdr(USER_CONSULTANT), json={"query": "数字化成熟度", "scope": "company"}
    )
    assert refreshed.status_code == 200
    l2_after = next(c for c in refreshed.json()["cards"] if c["asset_id"] == str(KA_COMPANY_L2))
    assert l2_after["detailed"].startswith("（脱敏）")
    assert l2_after["can_view_original"] is False


async def test_stage1_score_sorted_and_orphan_dropped(client):
    docs = [
        {"knowledge_id": _ORPHAN_DOC, "kb_id": _COMPANY_KB, "content": "孤儿无映射内容"},
        _doc(KA_COMPANY_L2, _COMPANY_KB, "零售数字化成熟度评估内容"),
    ]
    _install(FakeSearchWeKnora(docs), FakeScrubLLM())
    resp = await client.post(
        SEARCH, headers=_hdr(USER_CONSULTANT), json={"query": "成熟度", "scope": "company"}
    )
    body = resp.json()
    ids = [c["asset_id"] for c in body["cards"]]
    # 孤儿 knowledge 无业务映射 → 丢弃，不透出。
    assert str(KA_COMPANY_L2) in ids
    assert all("orphan" not in i for i in ids)


async def test_global_search_uses_cross_project_redacted_summary_not_chunks_or_members(client):
    docs = [_doc(KA_PROJECT_BETA_L3, _BETA_KB, _SENSITIVE)]
    _install(FakeSearchWeKnora(docs), FakeScrubLLM())
    resp = await client.post(
        SEARCH,
        headers=_hdr(USER_CONSULTANT),
        json={"query": "客户访谈", "scope": "all", "intent": "qa"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    card = next(card for card in body["cards"] if card["asset_id"] == str(KA_PROJECT_BETA_L3))
    assert card["detailed"].startswith("（脱敏）")
    assert card["can_view_original"] is False
    assert card["owner_name"] is None
    assert card["maintainer_name"] is None
    assert card["phase"] is None
    assert body["citations"][0]["used_access_layer"] == "summary"
    assert _SENSITIVE not in resp.text
    _assert_no_leak(resp.text)


async def test_active_non_member_project_filter_is_accepted_with_per_asset_summary_policy(client):
    docs = [_doc(KA_PROJECT_BETA_L3, _BETA_KB, _SENSITIVE)]
    _install(FakeSearchWeKnora(docs), FakeScrubLLM())
    response = await client.post(
        SEARCH,
        headers=_hdr(USER_CONSULTANT),
        json={
            "query": "客户访谈",
            "scope": "project",
            "filters": {"project_id": str(PROJECT_BETA)},
        },
    )

    assert response.status_code == 200
    assert {card["asset_id"] for card in response.json()["cards"]} == {str(KA_PROJECT_BETA_L3)}
    assert response.json()["cards"][0]["can_view_original"] is False
    assert _SENSITIVE not in response.text


async def test_cross_project_original_request_returns_no_chunks_or_member_names(client):
    docs = [_doc(KA_PROJECT_BETA_L3, _BETA_KB, _SENSITIVE)]
    _install(FakeSearchWeKnora(docs), FakeScrubLLM())
    resp = await client.post(
        SEARCH,
        headers=_hdr(USER_CONSULTANT),
        json={
            "query": "客户访谈",
            "scope": "all",
            "want_original": True,
            "asset_id": str(KA_PROJECT_BETA_L3),
        },
    )
    assert resp.status_code == 200
    original = resp.json()["original"]
    assert original == {
        "asset_id": str(KA_PROJECT_BETA_L3),
        "available": False,
        "chunks": [],
        "degraded_reason": "original_requires_request",
        "owner_name": None,
        "maintainer_name": None,
    }
    assert _SENSITIVE not in resp.text
    _assert_no_leak(resp.text)


# ---------------- 阶段2原文 + 输出脱敏 ----------------
async def test_stage2_original_desensitized_for_member(client, db_session):
    await _insert_alpha_l4(db_session)
    docs = [_doc(KA_ALPHA_L4, _ALPHA_KB, _SENSITIVE)]
    _install(FakeSearchWeKnora(docs), FakeScrubLLM())
    resp = await client.post(
        SEARCH,
        headers=_hdr(USER_CONSULTANT),
        json={
            "query": "交付物",
            "scope": "project",
            "want_original": True,
            "asset_id": str(KA_ALPHA_L4),
        },
    )
    assert resp.status_code == 200, resp.text
    original = resp.json()["original"]
    assert original["available"] is True
    joined = " ".join(c["content"] for c in original["chunks"])
    # L4 原文经 LLM 输出脱敏：客户敏感实体已被擦洗。
    assert "客户敏感实体XYZ" not in joined
    assert "888万元" not in joined
    assert "【客户】" in joined or "【金额】" in joined
    _assert_no_leak(resp.text)


async def test_stage2_no_permission_no_original_chunk(client):
    # consultant 对公司 L4 无原文权 → 只给卡片+联系人，断言无任何原文 chunk。
    docs = [_doc(KA_COMPANY_L4, _COMPANY_KB, _SENSITIVE)]
    _install(FakeSearchWeKnora(docs), FakeScrubLLM())
    resp = await client.post(
        SEARCH,
        headers=_hdr(USER_CONSULTANT),
        json={
            "query": "集采",
            "scope": "company",
            "want_original": True,
            "asset_id": str(KA_COMPANY_L4),
        },
    )
    assert resp.status_code == 200
    original = resp.json()["original"]
    assert original["available"] is False
    assert original["chunks"] == []
    assert original["degraded_reason"]  # original_requires_request 等
    # 无权调用方拿不到任何原文片段，也不泄露敏感实体。
    assert "客户敏感实体XYZ" not in resp.text
    _assert_no_leak(resp.text)


async def test_stage2_llm_down_conservative_no_original(client, db_session):
    await _insert_alpha_l4(db_session)
    docs = [_doc(KA_ALPHA_L4, _ALPHA_KB, _SENSITIVE)]
    # 有原文权（成员），但脱敏 LLM 不可用 → 保守降级：不返回原文。
    _install(FakeSearchWeKnora(docs), DownLLM())
    resp = await client.post(
        SEARCH,
        headers=_hdr(USER_CONSULTANT),
        json={
            "query": "交付物",
            "scope": "project",
            "want_original": True,
            "asset_id": str(KA_ALPHA_L4),
        },
    )
    assert resp.status_code == 200
    original = resp.json()["original"]
    assert original["available"] is False
    assert original["degraded_reason"] == "desensitization_unavailable"
    assert "客户敏感实体XYZ" not in resp.text


async def test_stage2_noop_desensitization_fails_closed(client, db_session):
    await _insert_alpha_l4(db_session)
    docs = [_doc(KA_ALPHA_L4, _ALPHA_KB, _SENSITIVE)]
    # 有原文权（成员），LLM 把原文原样返回（脱敏 no-op）→ fail-closed：不返回原文。
    _install(FakeSearchWeKnora(docs), NoOpScrubLLM())
    resp = await client.post(
        SEARCH,
        headers=_hdr(USER_CONSULTANT),
        json={
            "query": "交付物",
            "scope": "project",
            "want_original": True,
            "asset_id": str(KA_ALPHA_L4),
        },
    )
    assert resp.status_code == 200
    original = resp.json()["original"]
    assert original["available"] is False
    assert original["chunks"] == []
    assert original["degraded_reason"] == "desensitization_unavailable"
    # 绝不外泄未脱敏原文样本。
    assert "客户敏感实体XYZ" not in resp.text
    assert "888万元" not in resp.text


def test_audit_redacts_weknora_chunk_refs():
    """审计兜底脱敏：server-only chunk ref 键被剔除、wk-doc/wk-kb 值整串脱敏。"""
    from app.services import audit as audit_service

    # 值级：wk-doc / wk-kb 形态整串脱敏（即便经无害键名落库也被擦洗）。
    assert audit_service.sanitize_text("wk-doc-1234abcd#0") == "[redacted]"
    assert audit_service.sanitize_text("wk-kb-proj-abcd") == "[redacted]"
    # 键级：server-only chunk ref 键被剔除；无害安全键（intent 等）保留。
    cleaned = audit_service._sanitize(
        {
            "cited_weknora_chunk_ref": "wk-doc-x#0",
            "target_weknora_chunk_ref": "wk-doc-y#1",
            "weknora_chunk_ref": "wk-doc-z#2",
            "intent": "qa",
        }
    )
    assert "cited_weknora_chunk_ref" not in cleaned
    assert "target_weknora_chunk_ref" not in cleaned
    assert "weknora_chunk_ref" not in cleaned
    assert cleaned["intent"] == "qa"


# ---------------- 问答 ----------------
@pytest.mark.parametrize("slow_stage", ["recall", "evidence", "answer", "cumulative"])
async def test_qa_shared_deadline_cancels_slow_stage_and_never_fabricates_answer(
    client, db_session, monkeypatch, caplog, slow_stage
):
    from sqlalchemy import select

    from app.models.audit import AuditEvent
    from app.services import retrieval
    from app.services import search as search_service

    monkeypatch.setattr(search_service, "_qa_timeout_seconds", lambda _: 0.2)
    cancelled = asyncio.Event()

    async def slow(*args, **kwargs):
        try:
            await asyncio.sleep(5)
        finally:
            cancelled.set()

    docs = [_doc(KA_PROJECT_ALPHA, _ALPHA_KB, "Alpha 供应链优化。")]
    upstream = FakeSearchWeKnora(docs)
    llm = FakeScrubLLM()
    if slow_stage == "recall":
        monkeypatch.setattr(upstream, "search", slow)
    elif slow_stage == "cumulative":
        from app.services import search_queries

        original_search = upstream.search

        async def plan(*args, **kwargs):
            await asyncio.sleep(0.15)
            return [args[1]]

        async def delayed_search(*args, **kwargs):
            try:
                await asyncio.sleep(0.15)
                return await original_search(*args, **kwargs)
            finally:
                cancelled.set()

        monkeypatch.setattr(search_queries, "plan_queries", plan)
        monkeypatch.setattr(upstream, "search", delayed_search)
    elif slow_stage == "evidence":
        monkeypatch.setattr(retrieval, "gather_parent_context", slow)
    else:
        monkeypatch.setattr(llm, "chat_completion", slow)
    _install(upstream, llm)
    response = await asyncio.wait_for(
        client.post(
            SEARCH,
            headers=_hdr(USER_CONSULTANT),
            json={"query": "如何做供应链优化？", "scope": "project"},
        ),
        timeout=2,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert cancelled.is_set()
    assert body["answer_status"] == "unavailable"
    assert body["answer"] is None and body["citations"] == []
    assert body["answer_message"]
    assert "knowledge_qa_deadline" in caplog.text
    if slow_stage not in {"recall", "cumulative"}:
        assert body["cards"]
    _assert_no_leak(response.text)
    audit = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.trace_id == body["trace_id"],
                AuditEvent.action == "knowledge.searched",
            )
        )
    ).scalar_one()
    assert audit.extra["answer_status"] == "unavailable"
    assert audit.extra["timeout_stage"] == ("recall" if slow_stage == "cumulative" else slow_stage)
    assert "供应链" not in json.dumps(audit.extra, ensure_ascii=False)


async def test_qa_answer_and_citations_from_allowed_chunks(client):
    docs = [_doc(KA_PROJECT_ALPHA, _ALPHA_KB, "Alpha 供应链优化：采购、仓储、物流要点。")]
    _install(FakeSearchWeKnora(docs), FakeScrubLLM())
    resp = await client.post(
        SEARCH,
        headers=_hdr(USER_CONSULTANT),
        json={
            "query": "如何做供应链优化？",
            "scope": "project",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["intent"] == "qa"
    assert body["answer"]
    assert len(body["citations"]) >= 1
    for c in body["citations"]:
        assert c["scope"] == "project"
        assert c["used_access_layer"] in ("summary", "original")
        assert c["snippet"]
    _assert_no_leak(resp.text)


async def test_search_intent_default_no_answer(client):
    docs = [_doc(KA_PROJECT_ALPHA, _ALPHA_KB, "Alpha 供应链优化交付报告内容。")]
    _install(FakeSearchWeKnora(docs), FakeScrubLLM())
    resp = await client.post(
        SEARCH,
        headers=_hdr(USER_CONSULTANT),
        json={
            "query": "供应链优化交付报告",
            "scope": "project",
        },
    )
    body = resp.json()
    # 查找意图：只给卡片，不附答案。
    assert body["intent"] == "search"
    assert body["answer"] is None
    assert body["citations"] == []
    assert len(body["cards"]) >= 1


async def test_l5_director_can_discover(client):
    # 咨询总监可发现 L5 → 公司 L5 出现在卡片（对照 consultant 不可见）。
    docs = [_doc(KA_COMPANY_L5, _COMPANY_KB, "公司级绝密战略备忘原文")]
    _install(FakeSearchWeKnora(docs), FakeScrubLLM())
    resp = await client.post(
        SEARCH, headers=_hdr(USER_DIRECTOR), json={"query": "战略", "scope": "company"}
    )
    ids = {c["asset_id"] for c in resp.json()["cards"]}
    assert str(KA_COMPANY_L5) in ids


@pytest.mark.parametrize("query", ["通用检索验收", "独立标签锚点"])
async def test_metadata_match_survives_empty_chunk_recall(client, db_session, query):
    asset = await db_session.get(KnowledgeAsset, KA_COMPANY_L2)
    asset.title = "通用检索验收操作手册"
    db_session.add(KnowledgeAssetTag(asset_id=asset.id, tag_name="独立标签锚点"))
    await db_session.commit()
    _install(FakeSearchWeKnora([]), FakeScrubLLM())
    response = await client.post(
        SEARCH, headers=_hdr(USER_CONSULTANT), json={"query": query, "scope": "company"}
    )
    assert response.status_code == 200
    assert [card["asset_id"] for card in response.json()["cards"]] == [str(asset.id)]
    assert "wk-doc" not in response.text


async def test_tags_are_applied_before_chunk_recall(client, db_session):
    db_session.add(KnowledgeAssetTag(asset_id=KA_COMPANY_L2, tag_name="限定候选标签"))
    await db_session.commit()
    fake = FakeSearchWeKnora(
        [
            _doc(KA_COMPANY_L4, _COMPANY_KB, "unrelated high scoring chunks"),
            _doc(KA_COMPANY_L2, _COMPANY_KB, "filtered result"),
        ]
    )
    _install(fake, FakeScrubLLM())
    response = await client.post(
        SEARCH,
        headers=_hdr(USER_CONSULTANT),
        json={"query": "not a title", "scope": "company", "filters": {"tags": ["限定候选标签"]}},
    )
    assert response.status_code == 200
    assert fake.last_knowledge_ids == [f"wk-doc-{KA_COMPANY_L2}"]
    assert [card["asset_id"] for card in response.json()["cards"]] == [str(KA_COMPANY_L2)]


async def test_literal_match_is_not_crowded_out_by_upstream_score_scale(client, db_session):
    asset = await db_session.get(KnowledgeAsset, KA_COMPANY_L2)
    asset.title = "检索高分挤占回归手册"
    await db_session.commit()
    _install(
        FakeSearchWeKnora([_doc(KA_COMPANY_L4, _COMPANY_KB, "semantic result")]), FakeScrubLLM()
    )
    response = await client.post(
        SEARCH, headers=_hdr(USER_CONSULTANT), json={"query": "高分挤占回归", "scope": "company"}
    )
    assert response.status_code == 200
    assert response.json()["cards"][0]["asset_id"] == str(asset.id)


@pytest.mark.parametrize(
    "spoken,tagged_cases,earlier_tag",
    [(False, False, False), (False, True, False), (True, True, False), (True, True, True)],
)
async def test_specific_title_survives_more_than_one_hundred_visible_matches(
    client, db_session, monkeypatch, spoken, tagged_cases, earlier_tag
):
    from app.services import search_queries

    query = "独立排序锚点"
    for index in range(110):
        asset_id, version_id = uuid.uuid4(), uuid.uuid4()
        db_session.add(
            KnowledgeAsset(
                id=asset_id,
                title=f"案例{index:03}"
                if tagged_cases
                else f"{query}编号法规汇编与历史案例操作指引{index:03}",
                scope="company",
                zone="material",
                asset_type="unclassified",
                owner_user_id=USER_CONSULTANT,
                confidentiality_level="L2",
                ai_access_level="A1",
                current_version_id=version_id,
                asset_status="active",
            )
        )
        if tagged_cases:
            db_session.add(
                KnowledgeAssetTag(
                    asset_id=asset_id, tag_name="独立泛化标签" if earlier_tag else query
                )
            )
        db_session.add(
            KnowledgeAssetVersion(
                id=version_id,
                asset_id=asset_id,
                version_no="V1",
                version_status="active",
                created_by=USER_CONSULTANT,
                weknora_kb_id=_COMPANY_KB,
                weknora_doc_id=f"wk-ranking-{index}",
                index_status="indexed",
            )
        )
    target = await db_session.get(KnowledgeAsset, KA_COMPANY_L2)
    target.title = f"{query}手册"
    if earlier_tag:
        db_session.add(KnowledgeAssetTag(asset_id=target.id, tag_name="独立泛化标签"))
    await db_session.commit()
    _install(FakeSearchWeKnora([]), FakeScrubLLM())
    request_query = (
        "我想了解怎样把某种经营目标变成可以操作和复核的一套通用步骤？" if spoken else query
    )

    async def plan(*args, **kwargs):
        if earlier_tag:
            return [request_query, "独立泛化标签", query]
        return [request_query, query] if spoken else [query]

    monkeypatch.setattr(search_queries, "plan_queries", plan)
    response = await client.post(
        SEARCH, headers=_hdr(USER_CONSULTANT), json={"query": request_query, "scope": "company"}
    )
    assert response.status_code == 200
    assert len(response.json()["cards"]) == 100
    assert response.json()["cards"][0]["asset_id"] == str(target.id)


async def test_metadata_query_treats_sql_wildcards_as_literal_text(client):
    _install(FakeSearchWeKnora([]), FakeScrubLLM())
    response = await client.post(
        SEARCH, headers=_hdr(USER_CONSULTANT), json={"query": "%_", "scope": "company"}
    )
    assert response.status_code == 200
    assert response.json()["cards"] == []


@pytest.mark.parametrize("query", ["", "  ", "\t\n", "\u3000"])
async def test_blank_query_cannot_enumerate_assets(client, db_session, query):
    from app.schemas.permission import AccessChannel, CallerContext
    from app.services.retrieval import recall_assets

    class NoSearch:
        async def search(self, **kwargs):
            raise AssertionError("Blank queries must not reach upstream search")

    caller = CallerContext(
        user_id=USER_CONSULTANT,
        is_active=True,
        active_company_roles={"consultant"},
        active_project_ids=set(),
    )
    assert (
        await recall_assets(
            db_session,
            caller,
            NoSearch(),
            query=query,
            kb_ids=[_COMPANY_KB],
            channel=AccessChannel.human,
        )
        == []
    )
    response = await client.post(
        SEARCH, headers=_hdr(USER_CONSULTANT), json={"query": query, "scope": "company"}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["denied_reason"] == "query_required"


@pytest.mark.parametrize(
    "budget, early_visible, semantic",
    [
        (2000, False, False),
        (100, False, False),
        (101, False, True),
        (1, True, True),
    ],
)
async def test_metadata_scan_budget_preserves_permitted_hits(
    client, db_session, monkeypatch, caplog, budget, early_visible, semantic
):
    from app.services import retrieval

    monkeypatch.setattr(retrieval, "_METADATA_MAX_SCAN_ROWS", budget)
    query = "分页可见验收"
    for index in range(105):
        asset_id, version_id = uuid.uuid4(), uuid.uuid4()
        db_session.add(
            KnowledgeAsset(
                id=asset_id,
                title=f"A {query} {index:03}",
                scope="company",
                zone="material",
                asset_type="unclassified",
                owner_user_id=USER_CONSULTANT,
                confidentiality_level="L5",
                ai_access_level="A1",
                asset_status="active",
                current_version_id=version_id,
            )
        )
        db_session.add(
            KnowledgeAssetVersion(
                id=version_id,
                asset_id=asset_id,
                version_no="V1",
                version_status="active",
                created_by=USER_CONSULTANT,
                weknora_kb_id=_COMPANY_KB,
                weknora_doc_id=f"wk-hidden-{index}",
                index_status="indexed",
            )
        )
    visible = await db_session.get(KnowledgeAsset, KA_COMPANY_L2)
    visible.title = f"{query}早期候选" if early_visible else f"Z {query} 最后一个长标题可见候选"
    await db_session.commit()
    docs = [_doc(KA_COMPANY_L4, _COMPANY_KB, "semantic match")] if semantic else []
    _install(FakeSearchWeKnora(docs), FakeScrubLLM())
    response = await client.post(
        SEARCH, headers=_hdr(USER_CONSULTANT), json={"query": query, "scope": "company"}
    )
    assert response.status_code == 200
    expected = {str(visible.id)} if budget == 2000 or early_visible else set()
    if semantic:
        expected.add(str(KA_COMPANY_L4))
    assert {card["asset_id"] for card in response.json()["cards"]} == expected
    warnings = [
        record
        for record in caplog.records
        if record.message == "retrieval_metadata_scan_budget_exhausted"
    ]
    if budget < 2000:
        assert len(warnings) == 1
        assert warnings[0].scanned_rows == budget
        assert query not in warnings[0].getMessage()
    else:
        assert warnings == []
    assert "wk-hidden" not in response.text


@pytest.mark.parametrize(
    "invalid", ["archived", "stale", "failed", "pending", "other_kb", "denied"]
)
async def test_metadata_recall_keeps_all_security_gates(client, db_session, invalid):
    asset = await db_session.get(KnowledgeAsset, KA_COMPANY_L2)
    version = await db_session.get(KnowledgeAssetVersion, asset.current_version_id)
    asset.title = "隔离检索唯一锚点"
    if invalid == "archived":
        asset.asset_status = "archived"
    elif invalid == "stale":
        asset.current_version_id = uuid.uuid4()
    elif invalid == "failed":
        version.index_status = "index_failed"
    elif invalid == "pending":
        version.directory_key = "personal.pending"
    elif invalid == "other_kb":
        version.weknora_kb_id = "inaccessible-kb"
    else:
        asset.scope = "personal"
        asset.owner_user_id = USER_DIRECTOR
    await db_session.commit()
    _install(FakeSearchWeKnora([]), FakeScrubLLM())
    response = await client.post(
        SEARCH,
        headers=_hdr(USER_CONSULTANT),
        json={"query": "隔离检索唯一锚点", "scope": "company"},
    )
    assert response.status_code == 200
    assert response.json()["cards"] == []


async def test_spoken_query_expansion_preserves_scope_filters_and_permissions(
    client, db_session, monkeypatch
):
    from app.services import search_queries

    query = "说不出正式名称时如何找到那个按固定周期核查资料的通用流程？"
    term = "复核机制验收锚点"
    for asset_id in (KA_COMPANY_L2, KA_COMPANY_L5, KA_PROJECT_ALPHA):
        asset = await db_session.get(KnowledgeAsset, asset_id)
        asset.title = f"{term}手册"
        db_session.add(KnowledgeAssetTag(asset_id=asset_id, tag_name="独立扩展验收标签"))
    await db_session.commit()

    async def plan(*args, **kwargs):
        return [query, term]

    monkeypatch.setattr(search_queries, "plan_queries", plan)

    class RecordingSearch(FakeSearchWeKnora):
        def __init__(self):
            super().__init__([])
            self.calls = []

        async def search(self, **kwargs):
            self.calls.append(kwargs)
            return []

    fake = RecordingSearch()
    _install(fake, FakeScrubLLM())
    response = await client.post(
        SEARCH,
        headers=_hdr(USER_CONSULTANT),
        json={
            "query": query,
            "scope": "company",
            "intent": "search",
            "filters": {"tags": ["独立扩展验收标签"]},
        },
    )
    assert response.status_code == 200
    assert [card["asset_id"] for card in response.json()["cards"]] == [str(KA_COMPANY_L2)]
    assert [call["query"] for call in fake.calls] == [query, term]
    assert all(call["kb_ids"] == [_COMPANY_KB] for call in fake.calls)
    assert fake.calls[0]["knowledge_ids"] == fake.calls[1]["knowledge_ids"]
    assert str(KA_COMPANY_L5) not in response.text
    assert str(KA_PROJECT_ALPHA) not in response.text


async def test_optional_query_failure_preserves_primary_hits(client, monkeypatch, caplog):
    from app.services import search_queries
    from app.services.weknora_client import WeKnoraError

    query = "怎样查看已有资料在核查和确认后的处理流程以及相关说明？"

    async def plan(*args, **kwargs):
        return [query, "扩展查询"]

    monkeypatch.setattr(search_queries, "plan_queries", plan)

    class FailingExpansion(FakeSearchWeKnora):
        async def search(self, **kwargs):
            if kwargs["query"] != query:
                raise WeKnoraError("network_error", "SECRET-source-endpoint")
            return await super().search(**kwargs)

    _install(
        FailingExpansion([_doc(KA_COMPANY_L2, _COMPANY_KB, "primary evidence")]), FakeScrubLLM()
    )
    response = await client.post(
        SEARCH,
        headers=_hdr(USER_CONSULTANT),
        json={"query": query, "scope": "company", "intent": "search"},
    )
    assert response.status_code == 200
    assert [card["asset_id"] for card in response.json()["cards"]] == [str(KA_COMPANY_L2)]
    assert "SECRET" not in response.text + caplog.text
    assert "retrieval_optional_query_unavailable" in caplog.text

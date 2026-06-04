"""PBC-01 provider 中立外部 Agent 网关核心测试（不经任何 provider 适配器）。

直接针对 `app.services.external_agent_gateway`：
- 调用人解析 fail-closed（None / 未知 / 非 active → None）。
- 知识选择器解析 provider 中立语法。
- run_retrieval 返回 provider 中立 `ExternalRetrievalRecord`，metadata 只含安全业务标识，
  绝不含 provider 内部标识 / WeKnora id / 未脱敏原文。
"""

from __future__ import annotations

import uuid

from app.models.agent_registry import AgentWhitelistRule
from app.schemas.external_agent import ExternalRetrievalRecord
from app.services import external_agent_gateway as gateway
from app.services.agent_registry import hash_token
from app.seed.dev_seed import KA_PROJECT_ALPHA, PROJECT_ALPHA, USER_CONSULTANT

_ALPHA_KB = f"wk-kb-proj-{PROJECT_ALPHA}"

_LEAK_TOKENS = [
    "wk-kb", "wk-doc", "weknora", "kb_id", "doc_id", "chunk_id",
    "dataset_id", "workflow_id", "external_app_id", "external_workflow_id",
    "api_key", "token_hash", "storage_ref", "dify-secret",
]


class FakeSearchWeKnora:
    def __init__(self, docs):
        self.docs = docs

    async def search(self, *, query, kb_ids, knowledge_ids=None, top_k=20, trace_id=None):
        out = []
        for i, d in enumerate(self.docs):
            if d["kb_id"] not in kb_ids:
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
        return "【答案】"


def _rule():
    return AgentWhitelistRule(
        provider="dify", agent_identifier=f"agent-{uuid.uuid4().hex[:8]}",
        agent_name="中立网关测试接入", capability="qa",
        allowed_scope=None, allowed_project_id=None,
        max_confidentiality_level="L5", max_ai_access_level="A4",
        token_hash=hash_token("kgw_neutral_test"), enabled=True,
        external_app_id="provider-secret-app", external_workflow_id="provider-secret-wf",
    )


# ---------------- 调用人解析 fail-closed ----------------
async def test_resolve_caller_fail_closed(db_session):
    assert await gateway.resolve_caller(db_session, None) is None
    assert await gateway.resolve_caller(db_session, uuid.uuid4()) is None
    caller = await gateway.resolve_caller(db_session, USER_CONSULTANT)
    assert caller is not None and caller.is_business_user


# ---------------- 知识选择器（provider 中立语法）----------------
def test_parse_knowledge_selector_forms():
    assert gateway.parse_knowledge_selector("all") == (None, None, None)
    assert gateway.parse_knowledge_selector("company") == ("company", None, None)
    scope, pid, owner = gateway.parse_knowledge_selector(f"project:{PROJECT_ALPHA}")
    assert scope == "project" and pid == PROJECT_ALPHA and owner is None
    scope, pid, owner = gateway.parse_knowledge_selector(f"personal:{USER_CONSULTANT}")
    assert scope == "personal" and owner == USER_CONSULTANT
    assert gateway.parse_knowledge_selector("bogus-format") is None
    assert gateway.parse_knowledge_selector("project:not-a-uuid") is None


# ---------------- 中立检索：安全 record 形态 + 无泄露 ----------------
async def test_run_retrieval_returns_neutral_records(db_session):
    weknora = FakeSearchWeKnora([
        {"knowledge_id": f"wk-doc-{KA_PROJECT_ALPHA}", "kb_id": _ALPHA_KB,
         "content": "Alpha 供应链优化：采购、仓储、物流要点。"}
    ])
    caller = await gateway.resolve_caller(db_session, USER_CONSULTANT)
    records = await gateway.run_retrieval(
        db_session, caller, _rule(),
        knowledge_selector=f"project:{PROJECT_ALPHA}", query="供应链优化",
        top_k=3, score_threshold=0.0, weknora=weknora, llm=FakeLLM(), trace_id="trc-pbc01",
    )
    assert records is not None and len(records) >= 1
    rec = records[0]
    # provider 中立类型，非 Dify 专属类型。
    assert isinstance(rec, ExternalRetrievalRecord)
    assert rec.content and rec.title
    # metadata 仅安全业务标识，绝不含 provider 内部标识 / WeKnora id。
    assert set(rec.metadata.keys()) == {"asset_id", "scope", "zone", "used_access_layer", "citation_order"}
    assert rec.metadata["scope"] == "project"
    blob = " ".join(str(r.model_dump()) for r in records)
    for t in _LEAK_TOKENS:
        assert t not in blob, f"中立 record 不应泄露 {t}"


async def test_run_retrieval_invalid_selector_returns_none(db_session):
    caller = await gateway.resolve_caller(db_session, USER_CONSULTANT)
    out = await gateway.run_retrieval(
        db_session, caller, _rule(),
        knowledge_selector="not-a-valid-selector", query="q",
        top_k=3, score_threshold=0.0, weknora=FakeSearchWeKnora([]), llm=FakeLLM(), trace_id=None,
    )
    assert out is None

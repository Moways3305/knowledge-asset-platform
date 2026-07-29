"""Provider 中立 agent-gateway 端点测试（caller 仅由 token 绑定解析）。"""

from __future__ import annotations

import uuid

import pytest

from app.main import app
from app.models.agent_registry import AgentWhitelistRule
from app.models.knowledge import KnowledgeAsset
from app.models.weknora import WeknoraKbMapping
from app.seed.dev_seed import (
    KA_COMPANY_L2,
    KA_COMPANY_L5,
    KA_PERSONAL,
    KA_PROJECT_ALPHA,
    PROJECT_ALPHA,
    USER_CONSULTANT,
    USER_CONSULTANT_ADMIN,
)
from app.services.agent_registry import hash_token
from app.services.llm_client import get_llm_client
from app.services.weknora_client import get_weknora_client

SEARCH = "/api/v1/agent-gateway/tools/knowledge-search"
PROJECTS = "/api/v1/agent-gateway/projects"
_TOKEN = "kgw_test_workbuddy_token"
_ALPHA_KB = f"wk-kb-proj-{PROJECT_ALPHA}"
_COMPANY_KB = "wk-kb-company"

_LEAK_TOKENS = [
    "wk-kb",
    "wk-doc",
    "weknora",
    "kb_id",
    "doc_id",
    "chunk_id",
    "dataset_id",
    "workflow_id",
    "external_app_id",
    "external_workflow_id",
    "api_key",
    "token_hash",
    "storage_ref",
]


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


class FakeLLM:
    provider = "deepseek"
    model = "deepseek-chat"

    async def chat_completion(
        self, messages, *, temperature=0.2, model=None, json_object=True, trace_id=None
    ):
        system = messages[0]["content"] if messages else ""
        if "脱敏" in system:
            text = messages[1]["content"] if len(messages) > 1 else ""
            return text.replace("客户XYZ", "【客户】")
        return "【答案】[1]"


def _install(docs):
    app.dependency_overrides[get_weknora_client] = lambda: FakeSearchWeKnora(docs)
    app.dependency_overrides[get_llm_client] = lambda: FakeLLM()


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.pop(get_weknora_client, None)
    app.dependency_overrides.pop(get_llm_client, None)


async def _insert_rule(
    db_session,
    *,
    token=_TOKEN,
    bound_user_id=USER_CONSULTANT,
    enabled=True,
    capability="qa",
    allowed_scope=None,
    self_service=False,
    max_conf="L5",
):
    rule = AgentWhitelistRule(
        provider="workbuddy",
        agent_identifier=(
            f"workbuddy:self:{bound_user_id}" if self_service else f"wb-{uuid.uuid4().hex[:8]}"
        ),
        agent_name="WorkBuddy 测试",
        capability=capability,
        allowed_scope=allowed_scope,
        max_confidentiality_level=max_conf,
        max_ai_access_level="A4",
        token_hash=hash_token(token),
        enabled=enabled,
        is_self_service=self_service,
        bound_user_id=bound_user_id,
    )
    db_session.add(rule)
    await db_session.commit()
    return rule


def _bearer(token=_TOKEN):
    return {"Authorization": f"Bearer {token}"}


async def test_missing_bearer_rejected(client, db_session):
    await _insert_rule(db_session)
    _install([_doc(KA_PROJECT_ALPHA, _ALPHA_KB, "Alpha 内容")])
    r = await client.post(SEARCH, json={"query": "q", "scope": "project"})
    assert r.status_code == 401


async def test_unbound_token_fails_closed(client, db_session):
    await _insert_rule(db_session, bound_user_id=None)
    _install([_doc(KA_PROJECT_ALPHA, _ALPHA_KB, "Alpha 内容")])
    r = await client.post(SEARCH, headers=_bearer(), json={"query": "q", "scope": "project"})
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "caller_unbound"


async def test_search_runs_via_agent_channel(client, db_session):
    await _insert_rule(db_session)
    _install([_doc(KA_PROJECT_ALPHA, _ALPHA_KB, "Alpha 供应链优化要点。")])
    r = await client.post(SEARCH, headers=_bearer(), json={"query": "供应链", "scope": "project"})
    assert r.status_code == 200, r.text
    assert len(r.json()["cards"]) >= 1
    for t in _LEAK_TOKENS:
        assert t not in r.text


async def test_self_service_search_follows_owner_for_l3_personal(client, db_session):
    asset = await db_session.get(KnowledgeAsset, KA_PERSONAL)
    asset.confidentiality_level = "L3"
    personal_kb = "wk-kb-personal-self-service"
    db_session.add(
        WeknoraKbMapping(
            scope="personal",
            owner_user_id=USER_CONSULTANT,
            project_id=None,
            weknora_kb_id=personal_kb,
            embedding_model_id="seed-embed",
            kb_name="personal_self_service",
            status="active",
        )
    )
    await _insert_rule(
        db_session,
        bound_user_id=USER_CONSULTANT,
        self_service=True,
        max_conf="L2",
    )
    _install([_doc(KA_PERSONAL, personal_kb, "本人 L3 方法论")])
    response = await client.post(
        SEARCH,
        headers=_bearer(),
        json={"query": "方法论", "scope": "personal"},
    )
    assert response.status_code == 200, response.text
    assert str(KA_PERSONAL) in {card["asset_id"] for card in response.json()["cards"]}


async def test_bearer_bound_dual_role_user_keeps_business_identity(client, db_session):
    await _insert_rule(db_session, bound_user_id=USER_CONSULTANT_ADMIN)
    _install([_doc(KA_COMPANY_L2, _COMPANY_KB, "公司业务知识")])

    response = await client.post(
        SEARCH,
        headers=_bearer(),
        json={"query": "业务", "scope": "company"},
    )

    assert response.status_code == 200, response.text
    assert str(KA_COMPANY_L2) in {card["asset_id"] for card in response.json()["cards"]}


async def test_client_supplied_user_id_is_ignored(client, db_session):
    """带 X-Platform-User-Id 也不能改变 caller（仍为绑定用户），不能冒充。"""
    await _insert_rule(db_session)
    _install([_doc(KA_PROJECT_ALPHA, _ALPHA_KB, "Alpha 内容")])
    r = await client.post(
        SEARCH,
        headers={**_bearer(), "X-Platform-User-Id": str(uuid.uuid4())},
        json={"query": "供应链", "scope": "project"},
    )
    assert r.status_code == 200  # 头被忽略，绑定用户照常可检索本项目
    assert len(r.json()["cards"]) >= 1


async def test_consultant_cannot_discover_l5(client, db_session):
    await _insert_rule(db_session)
    _install(
        [_doc(KA_COMPANY_L2, _COMPANY_KB, "公司 L2"), _doc(KA_COMPANY_L5, _COMPANY_KB, "L5 绝密")]
    )
    r = await client.post(SEARCH, headers=_bearer(), json={"query": "战略", "scope": "company"})
    assert r.status_code == 200
    ids = {c["asset_id"] for c in r.json()["cards"]}
    assert str(KA_COMPANY_L5) not in ids


async def test_projects_minimal_safe_fields(client, db_session):
    await _insert_rule(db_session)
    _install([])
    r = await client.get(PROJECTS, headers=_bearer())
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) >= 1
    item = items[0]
    assert set(item.keys()) == {"project_id", "name", "status"}
    assert "client_name" not in r.text

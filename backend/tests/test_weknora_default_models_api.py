"""平台默认模型配置 API 测试（PBC-38）。

覆盖：admin 可 GET/PUT；治理角色（boss/咨询总监）可 GET 不可 PUT；顾问 GET/PUT 均 403；
伪造 model_ref → 404；类型不匹配 → 422 安全错误；响应与审计绝不含真实 model_id。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.main import app
from app.models.audit import AuditEvent
from app.seed.dev_seed import (
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
)
from app.services.weknora_client import get_weknora_client
from app.services.weknora_models import _model_ref

BASE = "/api/v1/admin/weknora/default-models"
MODELS = "/api/v1/admin/weknora/models"
_RAW_IDS = ["mid-emb", "mid-chat", "mid-rerank"]


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


class FakeWK:
    """fake WeKnora：仅 list_models（含真实 server-only id + 类型）。"""

    def __init__(self):
        self.models = {
            "mid-emb": {
                "id": "mid-emb",
                "name": "text-embedding-v3",
                "type": "Embedding",
                "source": "remote",
                "status": "active",
                "parameters": {"provider": "aliyun"},
            },
            "mid-chat": {
                "id": "mid-chat",
                "name": "qwen-plus",
                "type": "KnowledgeQA",
                "source": "remote",
                "status": "active",
                "parameters": {"provider": "aliyun"},
            },
            "mid-rerank": {
                "id": "mid-rerank",
                "name": "rerank-v3",
                "type": "Rerank",
                "source": "remote",
                "status": "active",
                "parameters": {"provider": "aliyun"},
            },
        }

    async def list_models(self, *, trace_id=None):
        return list(self.models.values())


@pytest.fixture
def wk(monkeypatch):
    fake = FakeWK()
    monkeypatch.setattr("app.api.weknora_admin.weknora_enabled", lambda: True)
    app.dependency_overrides[get_weknora_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_weknora_client, None)


async def _refs(client) -> dict[str, str]:
    """admin 列模型，取 {前端类型别名: model_ref}。"""
    items = (await client.get(MODELS, headers=_hdr(USER_ADMIN_ONLY))).json()["items"]
    return {it["type"]: it["model_ref"] for it in items}


# ---------------------------------------------------------------------------
# admin 可 GET / PUT；只回 model_ref，无真实 id
# ---------------------------------------------------------------------------
async def test_admin_put_then_get_no_raw_id(client, wk):
    refs = await _refs(client)
    r = await client.put(
        BASE,
        headers=_hdr(USER_ADMIN_ONLY),
        json={"embedding_model_ref": refs["embedding"], "rerank_model_ref": refs["rerank"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["embedding"]["model_ref"] == refs["embedding"]
    assert body["embedding"]["model_ref"] != "mid-emb"
    assert body["embedding"]["name"] == "text-embedding-v3"
    assert body["rerank"]["model_ref"] == refs["rerank"]
    for tok in _RAW_IDS:
        assert tok not in r.text

    g = await client.get(BASE, headers=_hdr(USER_ADMIN_ONLY))
    assert g.status_code == 200, g.text
    assert g.json()["embedding"]["model_ref"] == refs["embedding"]
    assert g.json()["rerank"]["model_ref"] == refs["rerank"]
    for tok in _RAW_IDS:
        assert tok not in g.text


# ---------------------------------------------------------------------------
# 治理角色可 GET，不可 PUT；顾问全 403
# ---------------------------------------------------------------------------
async def test_governance_can_get_cannot_put(client, wk):
    for uid in (USER_BOSS, USER_DIRECTOR):
        g = await client.get(BASE, headers=_hdr(uid))
        assert g.status_code == 200, g.text
        p = await client.put(BASE, headers=_hdr(uid), json={})
        assert p.status_code == 403
        assert p.json()["detail"]["denied_reason"] == "weknora_admin_required"


async def test_consultant_forbidden_get_and_put(client, wk):
    g = await client.get(BASE, headers=_hdr(USER_CONSULTANT))
    assert g.status_code == 403
    assert g.json()["detail"]["denied_reason"] == "weknora_admin_required"
    p = await client.put(BASE, headers=_hdr(USER_CONSULTANT), json={})
    assert p.status_code == 403
    assert p.json()["detail"]["denied_reason"] == "weknora_admin_required"


# ---------------------------------------------------------------------------
# 伪造 ref → 404；类型不匹配 → 422 安全错误
# ---------------------------------------------------------------------------
async def test_fake_ref_returns_404(client, wk):
    r = await client.put(
        BASE, headers=_hdr(USER_ADMIN_ONLY), json={"embedding_model_ref": "deadbeef-not-a-ref"}
    )
    assert r.status_code == 404
    assert r.json()["detail"]["denied_reason"] == "weknora_model_not_found"


async def test_type_mismatch_returns_422(client, wk):
    refs = await _refs(client)
    # 把 chat 模型的 ref 设进 embedding 槽位 → 类型不匹配。
    r = await client.put(
        BASE, headers=_hdr(USER_ADMIN_ONLY), json={"embedding_model_ref": refs["chat"]}
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["denied_reason"] == "weknora_model_type_mismatch"
    for tok in _RAW_IDS:
        assert tok not in r.text


async def test_rerank_type_mismatch_returns_422(client, wk):
    refs = await _refs(client)
    # embedding 模型的 ref 设进 rerank 槽位 → 类型不匹配。
    r = await client.put(
        BASE, headers=_hdr(USER_ADMIN_ONLY), json={"rerank_model_ref": refs["embedding"]}
    )
    assert r.status_code == 422
    assert r.json()["detail"]["denied_reason"] == "weknora_model_type_mismatch"


async def test_unknown_model_family_cannot_be_saved_as_default(client, wk):
    wk.models["mid-invalid-default"] = {
        "id": "mid-invalid-default",
        "name": "random-model",
        "type": "Embedding",
        "source": "remote",
        "status": "active",
        "parameters": {"provider": "aliyun"},
    }

    response = await client.put(
        BASE,
        headers=_hdr(USER_ADMIN_ONLY),
        json={"embedding_model_ref": _model_ref("mid-invalid-default")},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["denied_reason"] == "weknora_model_name_invalid"

    defaults = await client.get(BASE, headers=_hdr(USER_ADMIN_ONLY))
    assert defaults.status_code == 200
    assert defaults.json()["embedding"] is None


# ---------------------------------------------------------------------------
# 审计：action 安全，extra 无真实 model_id，只含安全 model_ref
# ---------------------------------------------------------------------------
async def test_audit_has_no_raw_model_id(client, wk, db_session):
    refs = await _refs(client)
    r = await client.put(
        BASE, headers=_hdr(USER_ADMIN_ONLY), json={"embedding_model_ref": refs["embedding"]}
    )
    assert r.status_code == 200, r.text
    ev = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "weknora.default_models_updated")
            )
        )
        .scalars()
        .all()
    )
    assert len(ev) >= 1
    blob = str([e.extra for e in ev])
    for tok in _RAW_IDS:
        assert tok not in blob
    # extra 携带安全 model_ref（对底座 id 不可逆）。
    assert any((e.extra or {}).get("embedding_ref") == refs["embedding"] for e in ev)

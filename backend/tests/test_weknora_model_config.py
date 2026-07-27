"""模型配置中心测试。

覆盖：admin 读 provider/模型；非 admin 403；创建/更新模型 secret 只上送底座、响应/审计不回显；
删除用 server-only id、响应无真实 id；模型列表只回 model_ref 不回真实 id；kb-configs 不含
weknora_kb_id；更新 KB 初始化时前端传 model_ref、fake 收到真实 model id；未配置 503 只回缺失项名；
连通性测试不回 key/url/payload；审计只含安全字段。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.main import app
from app.models.audit import AuditEvent
from app.models.weknora import WeknoraKbMapping
from app.seed.dev_seed import USER_ADMIN_ONLY, USER_CONSULTANT
from app.services.weknora_client import WeKnoraError, get_weknora_client
from app.services.weknora_models import _model_ref

BASE = "/api/v1/admin/weknora"
_SECRET = "sk-secret-xyz-123"
_URL = "https://secret-host.example.com/v1"


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


class FakeModelsWK:
    """fake WeKnora 模型管理面：记录创建/更新/删除/初始化的真实入参。"""

    def __init__(self):
        # 预置若干模型（含真实 server-only id）。
        self.models: dict[str, dict] = {
            "mid-chat": {
                "id": "mid-chat",
                "name": "qwen-plus",
                "type": "KnowledgeQA",
                "source": "remote",
                "status": "active",
                "parameters": {
                    "provider": "aliyun",
                    "base_url": _URL,
                    "api_key": _SECRET,
                },
            },
            "mid-emb": {
                "id": "mid-emb",
                "name": "text-embedding-v3",
                "type": "Embedding",
                "source": "remote",
                "status": "active",
                "parameters": {
                    "provider": "aliyun",
                    "base_url": _URL,
                    "api_key": _SECRET,
                },
            },
        }
        self.last_create: dict | None = None
        self.last_update: dict | None = None
        self.deleted: list[str] = []
        self.last_init: dict | None = None
        self.last_check: dict | None = None
        self.list_calls = 0
        self.kb_configs: dict[str, dict] = {}
        self._n = 0

    async def list_model_providers(self, model_type=None, *, trace_id=None):
        return [
            {
                "value": "aliyun",
                "label": "阿里云 DashScope",
                "description": "qwen, etc.",
                "modelTypes": ["chat", "embedding"],
            }
        ]

    async def list_models(self, *, trace_id=None):
        self.list_calls += 1
        return list(self.models.values())

    async def get_model(self, model_id, *, trace_id=None):
        return self.models[model_id]

    async def create_model(self, payload, *, trace_id=None):
        self.last_create = payload
        self._n += 1
        mid = f"mid-new-{self._n}"
        self.models[mid] = {
            "id": mid,
            "name": payload["name"],
            "type": payload["type"],
            "source": payload["source"],
            "status": "active",
            "parameters": {"provider": payload.get("parameters", {}).get("provider")},
        }
        return self.models[mid]

    async def update_model(self, model_id, payload, *, trace_id=None):
        self.last_update = {"id": model_id, "payload": payload}
        self.models[model_id]["name"] = payload.get("name") or self.models[model_id]["name"]
        return self.models[model_id]

    async def delete_model(self, model_id, *, trace_id=None):
        self.deleted.append(model_id)
        self.models.pop(model_id, None)

    async def get_initialization_config(self, kb_id, *, trace_id=None):
        return {"hasFiles": False}

    async def get_kb(self, kb_id, *, trace_id=None):
        return self.kb_configs.get(
            kb_id,
            {
                "summary_model_id": "mid-chat",
                "embedding_model_id": "mid-emb",
                "chunking_config": {
                    "chunk_size": 640,
                    "chunk_overlap": 64,
                    "separators": ["\n\n", "\n"],
                    "enable_parent_child": True,
                    "parent_chunk_size": 2048,
                    "child_chunk_size": 256,
                },
                "vlm_config": {"enabled": False},
                "asr_config": {"enabled": False},
                "storage_provider_config": {"provider": "local"},
                "extract_config": {"enabled": False},
                "question_generation_config": {"enabled": False, "question_count": 4},
                "knowledge_count": 0,
            },
        )

    async def update_initialization_config(
        self,
        kb_id,
        *,
        config,
        trace_id=None,
    ):
        self.last_init = {
            "kb_id": kb_id,
            "config": config,
        }
        return {"success": True}

    async def check_remote_model(
        self,
        *,
        model_id,
        model_name,
        base_url,
        source,
        provider=None,
        interface_type=None,
        trace_id=None,
    ):
        self.last_check = {
            "type": "chat",
            "model_id": model_id,
            "model_name": model_name,
            "base_url": base_url,
            "source": source,
            "provider": provider,
            "interface_type": interface_type,
        }
        return {"success": True, "message": "模型可用"}

    async def test_embedding_model(
        self,
        *,
        model_id,
        model_name,
        base_url,
        source,
        provider=None,
        interface_type=None,
        trace_id=None,
    ):
        self.last_check = {
            "type": "embedding",
            "model_id": model_id,
            "model_name": model_name,
            "base_url": base_url,
            "source": source,
            "provider": provider,
            "interface_type": interface_type,
        }
        return {"success": True, "message": "嵌入模型测试通过"}

    async def check_rerank_model(self, **_):
        return {"success": True, "message": "重排序模型可用"}

    async def test_multimodal_model(self, **_):
        return {"success": True, "message": "多模态模型测试通过"}


@pytest.fixture
def wk(monkeypatch):
    fake = FakeModelsWK()
    monkeypatch.setattr("app.api.weknora_admin.weknora_enabled", lambda: True)
    app.dependency_overrides[get_weknora_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_weknora_client, None)


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------
async def test_admin_reads_providers_and_models(client, wk):
    p = await client.get(f"{BASE}/providers", headers=_hdr(USER_ADMIN_ONLY))
    assert p.status_code == 200
    assert p.json()["items"][0]["value"] == "aliyun"
    m = await client.get(f"{BASE}/models", headers=_hdr(USER_ADMIN_ONLY))
    assert m.status_code == 200
    items = m.json()["items"]
    assert len(items) == 2
    # 只回 model_ref，无真实 id / model_id。
    for it in items:
        assert "model_ref" in it and it["model_ref"]
        assert "id" not in it and "model_id" not in it
    assert "mid-chat" not in m.text and "mid-emb" not in m.text


async def test_consultant_forbidden(client, wk):
    for path in ("/providers", "/models", "/kb-configs"):
        r = await client.get(f"{BASE}{path}", headers=_hdr(USER_CONSULTANT))
        assert r.status_code == 403
        assert r.json()["detail"]["denied_reason"] == "weknora_operator_required"


# ---------------------------------------------------------------------------
# 模型创建 / 更新 / 删除：secret 只上送、不回显
# ---------------------------------------------------------------------------
async def test_create_model_secret_upstream_not_in_response_or_audit(client, wk, db_session):
    body = {
        "name": "qwen-max",
        "type": "chat",
        "source": "remote",
        "provider": "aliyun",
        "base_url": _URL,
        "api_key": _SECRET,
        "description": "测试",
    }
    r = await client.post(f"{BASE}/models", headers=_hdr(USER_ADMIN_ONLY), json=body)
    assert r.status_code == 200, r.text
    # fake（底座）确实收到了 secret。
    assert wk.last_create["parameters"]["api_key"] == _SECRET
    assert wk.last_create["parameters"]["base_url"] == _URL
    assert wk.last_create["name"] == "qwen-max"
    assert wk.last_create["type"] == "KnowledgeQA"  # alias→WeKnora 枚举
    # 平台响应不回显 secret / base_url / 真实 id。
    for token in [_SECRET, _URL, "sk-", "mid-new", "api_key", "base_url"]:
        assert token not in r.text
    assert r.json()["model_ref"]
    # 审计只含安全字段，不含 secret。
    ev = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "weknora.model_created")
            )
        )
        .scalars()
        .all()
    )
    assert len(ev) >= 1
    blob = str([e.extra for e in ev])
    for token in [_SECRET, _URL, "sk-", "mid-new"]:
        assert token not in blob
    assert any((e.extra or {}).get("provider") == "aliyun" for e in ev)


async def test_update_model_no_secret_leak(client, wk):
    models = (await client.get(f"{BASE}/models", headers=_hdr(USER_ADMIN_ONLY))).json()["items"]
    ref = models[0]["model_ref"]
    body = {
        "name": "deepseek-chat",
        "type": "chat",
        "source": "remote",
        "api_key": _SECRET,
        "base_url": _URL,
    }
    r = await client.put(f"{BASE}/models/{ref}", headers=_hdr(USER_ADMIN_ONLY), json=body)
    assert r.status_code == 200, r.text
    # 底座收到 server-only id（非 ref）+ secret。
    assert wk.last_update["id"] in wk.models
    assert wk.last_update["payload"]["name"] == "deepseek-chat"
    assert wk.last_update["payload"]["parameters"]["api_key"] == _SECRET
    for token in [_SECRET, _URL, "sk-"]:
        assert token not in r.text


async def test_update_model_blank_secret_fields_are_omitted(client, wk):
    models = (await client.get(f"{BASE}/models", headers=_hdr(USER_ADMIN_ONLY))).json()["items"]
    ref = models[0]["model_ref"]
    body = {
        "name": "qwen-turbo",
        "type": "chat",
        "source": "remote",
        "api_key": "",
        "base_url": "",
    }
    r = await client.put(f"{BASE}/models/{ref}", headers=_hdr(USER_ADMIN_ONLY), json=body)
    assert r.status_code == 200, r.text
    params = wk.last_update["payload"]["parameters"]
    assert "api_key" not in params
    assert "base_url" not in params


async def test_update_model_rejects_email_shaped_base_url_without_upstream_call(client, wk):
    models = (await client.get(f"{BASE}/models", headers=_hdr(USER_ADMIN_ONLY))).json()["items"]
    ref = models[0]["model_ref"]
    body = {
        "name": "qwen-plus",
        "type": "chat",
        "source": "remote",
        "api_key": _SECRET,
        "base_url": "alice@example.com",
    }
    r = await client.put(f"{BASE}/models/{ref}", headers=_hdr(USER_ADMIN_ONLY), json=body)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["denied_reason"] == "weknora_model_base_url_invalid"
    assert wk.last_update is None


@pytest.mark.parametrize("invalid_name", ["deepsekk", "deepsekk-v3", "random-model"])
async def test_create_model_rejects_unknown_name_without_upstream_call(client, wk, invalid_name):
    response = await client.post(
        f"{BASE}/models",
        headers=_hdr(USER_ADMIN_ONLY),
        json={
            "name": invalid_name,
            "type": "chat",
            "source": "remote",
            "provider": "aliyun",
            "base_url": _URL,
            "api_key": _SECRET,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["denied_reason"] == "weknora_model_name_invalid"
    assert wk.last_create is None


async def test_update_model_rejects_unknown_name_without_upstream_call(client, wk):
    models = (await client.get(f"{BASE}/models", headers=_hdr(USER_ADMIN_ONLY))).json()["items"]
    wk.list_calls = 0
    response = await client.put(
        f"{BASE}/models/{models[0]['model_ref']}",
        headers=_hdr(USER_ADMIN_ONLY),
        json={
            "name": "deepsekk-v3",
            "type": "chat",
            "source": "remote",
            "api_key": "",
            "base_url": "",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["denied_reason"] == "weknora_model_name_invalid"
    assert wk.last_update is None
    assert wk.list_calls == 0


async def test_list_models_excludes_unknown_upstream_names(client, wk):
    invalid_names = ["deepsekk", "deepsekk-v3", "random-model"]
    for index, name in enumerate(invalid_names):
        wk.models[f"mid-invalid-{index}"] = {
            "id": f"mid-invalid-{index}",
            "name": name,
            "type": "KnowledgeQA",
            "source": "remote",
            "status": "active",
            "parameters": {"provider": "aliyun"},
        }

    response = await client.get(f"{BASE}/models", headers=_hdr(USER_ADMIN_ONLY))

    assert response.status_code == 200
    listed_names = {item["name"] for item in response.json()["items"]}
    assert listed_names == {"qwen-plus", "text-embedding-v3"}
    assert listed_names.isdisjoint(invalid_names)


async def test_kb_config_rejects_unknown_model_family(client, wk, db_session):
    mapping = WeknoraKbMapping(
        scope="company",
        weknora_kb_id="kb-invalid-model-family",
        kb_name="company-invalid-model-family",
        status="active",
    )
    db_session.add(mapping)
    await db_session.commit()
    await db_session.refresh(mapping)
    wk.models["mid-invalid-kb"] = {
        "id": "mid-invalid-kb",
        "name": "random-model",
        "type": "Embedding",
        "source": "remote",
        "status": "active",
        "parameters": {"provider": "aliyun"},
    }

    response = await client.put(
        f"{BASE}/kb-configs/{mapping.id}/initialization",
        headers=_hdr(USER_ADMIN_ONLY),
        json={"embedding_model_ref": _model_ref("mid-invalid-kb")},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["denied_reason"] == "weknora_model_name_invalid"
    assert wk.last_init is None


async def test_delete_model_uses_server_id_no_leak(client, wk):
    models = (await client.get(f"{BASE}/models", headers=_hdr(USER_ADMIN_ONLY))).json()["items"]
    ref = models[0]["model_ref"]
    r = await client.delete(f"{BASE}/models/{ref}", headers=_hdr(USER_ADMIN_ONLY))
    assert r.status_code == 200
    assert r.json()["deleted"] is True
    # 删除用的是 server-only id（mid-*），响应不含真实 id。
    assert wk.deleted and wk.deleted[0].startswith("mid-")
    assert "mid-" not in r.text


# ---------------------------------------------------------------------------
# KB 初始化配置
# ---------------------------------------------------------------------------
async def test_kb_configs_no_kb_id_leak(client, wk):
    r = await client.get(f"{BASE}/kb-configs", headers=_hdr(USER_ADMIN_ONLY))
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 1
    # 平台 mapping_id 定位；绝不含 weknora_kb_id（seed 为 wk-kb-*）。
    for token in ["wk-kb-", "weknora_kb_id", "mid-"]:
        assert token not in r.text
    # 槽位用 model_ref。
    for it in items:
        for slot in ("chat", "embedding", "rerank", "multimodal"):
            if it.get(slot):
                assert "model_ref" in it[slot]


async def test_update_kb_init_resolves_ref_to_server_id(client, wk, db_session):
    # 取 company 映射 id + 一个 embedding 模型 ref。
    mp = (
        (
            await db_session.execute(
                select(WeknoraKbMapping).where(WeknoraKbMapping.scope == "company")
            )
        )
        .scalars()
        .first()
    )
    models = (await client.get(f"{BASE}/models", headers=_hdr(USER_ADMIN_ONLY))).json()["items"]
    emb_ref = next(m["model_ref"] for m in models if m["type"] == "embedding")
    r = await client.put(
        f"{BASE}/kb-configs/{mp.id}/initialization",
        headers=_hdr(USER_ADMIN_ONLY),
        json={"embedding_model_ref": emb_ref},
    )
    assert r.status_code == 200, r.text
    # 底座收到当前 camelCase 完整契约，未编辑的问答与切分配置保持不变。
    config = wk.last_init["config"]
    assert config["embeddingModelId"] == "mid-emb"
    assert config["embeddingModelId"] != emb_ref
    assert config["llmModelId"] == "mid-chat"
    assert config["documentSplitting"]["chunkSize"] == 640
    assert config["documentSplitting"]["enableParentChild"] is True
    assert not {
        "chat_model_id",
        "embedding_model_id",
        "rerank_model_id",
        "multimodal_id",
    }.intersection(config)
    assert "mid-emb" not in r.text and "wk-kb-" not in r.text


async def test_update_kb_init_merges_chat_and_embedding_after_upstream_success(
    client, wk, db_session
):
    wk.models["server-chat-next"] = {
        "id": "server-chat-next",
        "name": "qwen-next",
        "type": "KnowledgeQA",
        "source": "remote",
        "status": "active",
        "parameters": {"provider": "provider"},
    }
    wk.models["server-embedding-next"] = {
        "id": "server-embedding-next",
        "name": "embedding-next",
        "type": "Embedding",
        "source": "remote",
        "status": "active",
        "parameters": {"provider": "provider"},
    }
    mp = (
        (
            await db_session.execute(
                select(WeknoraKbMapping).where(WeknoraKbMapping.scope == "company")
            )
        )
        .scalars()
        .first()
    )
    models = (await client.get(f"{BASE}/models", headers=_hdr(USER_ADMIN_ONLY))).json()["items"]
    refs = {model["name"]: model["model_ref"] for model in models}

    response = await client.put(
        f"{BASE}/kb-configs/{mp.id}/initialization",
        headers=_hdr(USER_ADMIN_ONLY),
        json={
            "chat_model_ref": refs["qwen-next"],
            "embedding_model_ref": refs["embedding-next"],
        },
    )

    assert response.status_code == 200, response.text
    assert wk.last_init["config"]["llmModelId"] == "server-chat-next"
    assert wk.last_init["config"]["embeddingModelId"] == "server-embedding-next"
    assert wk.last_init["config"]["documentSplitting"]["separators"] == ["\n\n", "\n"]
    await db_session.refresh(mp)
    assert mp.embedding_model_id == "server-embedding-next"
    for token in ("server-chat-next", "server-embedding-next", "wk-kb-company"):
        assert token not in response.text


async def test_update_kb_init_keeps_embedding_locked_when_files_exist(client, wk, db_session):
    wk.models["server-embedding-next"] = {
        "id": "server-embedding-next",
        "name": "embedding-next",
        "type": "Embedding",
        "source": "remote",
        "status": "active",
        "parameters": {"provider": "provider"},
    }

    async def _with_files(kb_id, *, trace_id=None):
        return {"hasFiles": True}

    wk.get_initialization_config = _with_files
    mp = (
        (
            await db_session.execute(
                select(WeknoraKbMapping).where(WeknoraKbMapping.scope == "company")
            )
        )
        .scalars()
        .first()
    )
    models = (await client.get(f"{BASE}/models", headers=_hdr(USER_ADMIN_ONLY))).json()["items"]
    embedding_ref = next(
        model["model_ref"] for model in models if model["name"] == "embedding-next"
    )

    response = await client.put(
        f"{BASE}/kb-configs/{mp.id}/initialization",
        headers=_hdr(USER_ADMIN_ONLY),
        json={"embedding_model_ref": embedding_ref},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["denied_reason"] == "weknora_embedding_locked"
    assert wk.last_init is None


# ---------------------------------------------------------------------------
# 连通性测试 / 未配置
# ---------------------------------------------------------------------------
async def test_check_model_no_secret_in_response(client, wk):
    model_ref = _model_ref("mid-emb")
    r = await client.post(
        f"{BASE}/models/check",
        headers=_hdr(USER_ADMIN_ONLY),
        json={"model_ref": model_ref},
    )
    assert r.status_code == 200
    assert r.json()["success"] is True
    assert wk.list_calls == 1
    assert wk.last_check == {
        "type": "embedding",
        "model_id": "mid-emb",
        "model_name": "text-embedding-v3",
        "base_url": _URL,
        "source": "remote",
        "provider": "aliyun",
        "interface_type": None,
    }
    for token in [_SECRET, _URL, "sk-"]:
        assert token not in r.text


async def test_check_model_rejects_missing_saved_connection_before_upstream_call(client, wk):
    wk.models["mid-emb"]["parameters"] = {"provider": "aliyun"}
    r = await client.post(
        f"{BASE}/models/check",
        headers=_hdr(USER_ADMIN_ONLY),
        json={"model_ref": _model_ref("mid-emb")},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["denied_reason"] == "weknora_model_connection_config_missing"
    assert wk.last_check is None


async def test_check_model_fails_closed_for_multimodal_without_native_saved_model_contract(
    client, wk
):
    wk.models["mid-vllm"] = {
        "id": "mid-vllm",
        "name": "qwen-vl-plus",
        "type": "VLLM",
        "source": "remote",
        "status": "active",
        "parameters": {"provider": "aliyun"},
    }
    r = await client.post(
        f"{BASE}/models/check",
        headers=_hdr(USER_ADMIN_ONLY),
        json={"model_ref": _model_ref("mid-vllm")},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["denied_reason"] == "weknora_saved_model_check_unsupported"
    assert wk.last_check is None
    for token in [_URL, "mid-vllm", "api_key", "base_url"]:
        assert token not in r.text


async def test_not_configured_returns_safe_503(client, monkeypatch):
    # 不启用 WeKnora（默认 env 空）→ 503，只回缺失项名，不回值。
    monkeypatch.setattr("app.api.weknora_admin.weknora_enabled", lambda: False)
    r = await client.get(f"{BASE}/models", headers=_hdr(USER_ADMIN_ONLY))
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert detail["denied_reason"] == "weknora_not_configured"
    assert "WEKNORA_BASE_URL" in detail["missing_config"]
    for token in ["sk-", "http"]:
        assert token not in r.text


async def test_not_configured_consultant_still_403(client, monkeypatch):
    # 权限闸在 enabled 闸之前：非 admin 即使未配置也先 403。
    monkeypatch.setattr("app.api.weknora_admin.weknora_enabled", lambda: False)
    r = await client.get(f"{BASE}/models", headers=_hdr(USER_CONSULTANT))
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "weknora_operator_required"


# ---------------------------------------------------------------------------
# 上游错误 message 不得回显 secret / 内部标识
# ---------------------------------------------------------------------------
class _LeakyCreateWK(FakeModelsWK):
    async def create_model(self, payload, *, trace_id=None):
        raise WeKnoraError(
            "bad_request", f"bad {_SECRET} {_URL} mid-chat wk-kb-company api_key base_url"
        )


class _LeakyCheckWK(FakeModelsWK):
    async def test_embedding_model(self, **_):
        raise WeKnoraError("upstream_400", f"reject {_SECRET} {_URL} mid-emb")


class _LeakyInitWK(FakeModelsWK):
    async def update_initialization_config(self, kb_id, **_):
        raise WeKnoraError("init_400", f"fail {_SECRET} {_URL} {kb_id} mid-emb", status_code=400)


def _install(monkeypatch, fake):
    monkeypatch.setattr("app.api.weknora_admin.weknora_enabled", lambda: True)
    app.dependency_overrides[get_weknora_client] = lambda: fake


_LEAK_TOKENS = [_SECRET, _URL, "sk-", "mid-chat", "mid-emb", "wk-kb-company", "api_key", "base_url"]


async def test_model_create_upstream_error_no_leak(client, monkeypatch, db_session):
    _install(monkeypatch, _LeakyCreateWK())
    try:
        r = await client.post(
            f"{BASE}/models",
            headers=_hdr(USER_ADMIN_ONLY),
            json={
                "name": "deepseek-v4",
                "type": "chat",
                "source": "remote",
                "base_url": _URL,
                "api_key": _SECRET,
            },
        )
        assert r.status_code == 502, r.text
        assert r.json()["detail"]["message"] == "底座模型配置调用失败，请检查配置或稍后重试"
        for token in _LEAK_TOKENS:
            assert token not in r.text
        # 上游失败不写成功审计。
        ev = (
            (
                await db_session.execute(
                    select(AuditEvent).where(AuditEvent.action == "weknora.model_created")
                )
            )
            .scalars()
            .all()
        )
        assert ev == []
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_model_check_upstream_error_no_leak(client, monkeypatch):
    _install(monkeypatch, _LeakyCheckWK())
    try:
        r = await client.post(
            f"{BASE}/models/check",
            headers=_hdr(USER_ADMIN_ONLY),
            json={"model_ref": _model_ref("mid-emb")},
        )
        assert r.status_code == 502, r.text
        for token in _LEAK_TOKENS:
            assert token not in r.text
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_kb_init_upstream_error_no_leak(client, monkeypatch, db_session):
    _install(monkeypatch, _LeakyInitWK())
    try:
        mp = (
            (
                await db_session.execute(
                    select(WeknoraKbMapping).where(WeknoraKbMapping.scope == "company")
                )
            )
            .scalars()
            .first()
        )
        models = (await client.get(f"{BASE}/models", headers=_hdr(USER_ADMIN_ONLY))).json()["items"]
        emb_ref = next(m["model_ref"] for m in models if m["type"] == "embedding")
        original_status = mp.status
        original_embedding = mp.embedding_model_id
        r = await client.put(
            f"{BASE}/kb-configs/{mp.id}/initialization",
            headers=_hdr(USER_ADMIN_ONLY),
            json={"embedding_model_ref": emb_ref},
        )
        assert r.status_code == 502, r.text
        assert r.json()["detail"] == {
            "denied_reason": "weknora_kb_config_rejected",
            "message": "知识库配置被底座拒绝，请检查所选模型是否兼容",
        }
        await db_session.refresh(mp)
        assert mp.status == original_status
        assert mp.embedding_model_id == original_embedding
        saved = (
            (
                await db_session.execute(
                    select(AuditEvent).where(AuditEvent.action == "weknora.kb_config_updated")
                )
            )
            .scalars()
            .all()
        )
        assert saved == []
        for token in _LEAK_TOKENS + ["wk-kb-company"]:
            assert token not in r.text
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


# ---------------------------------------------------------------------------
# create_model 缺 upstream id → fail-closed，不假成功、不写成功审计
# ---------------------------------------------------------------------------
class _NoIdCreateWK(FakeModelsWK):
    async def create_model(self, payload, *, trace_id=None):
        return {"name": payload["name"], "type": payload["type"]}  # 无 id


async def test_create_model_missing_id_fails_closed(client, monkeypatch, db_session):
    _install(monkeypatch, _NoIdCreateWK())
    try:
        r = await client.post(
            f"{BASE}/models",
            headers=_hdr(USER_ADMIN_ONLY),
            json={
                "name": "qwen-plus",
                "type": "chat",
                "source": "remote",
                "base_url": _URL,
                "api_key": _SECRET,
            },
        )
        assert r.status_code == 502
        assert r.json()["detail"]["denied_reason"] == "weknora_model_create_no_id"
        assert "model_ref" not in r.text
        ev = (
            (
                await db_session.execute(
                    select(AuditEvent).where(AuditEvent.action == "weknora.model_created")
                )
            )
            .scalars()
            .all()
        )
        assert ev == []
        for token in _LEAK_TOKENS:
            assert token not in r.text
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


# ---------------------------------------------------------------------------
# WEKNORA_MODEL_REF_SECRET 缺失在 /health/config 标出（仅名，不回值）
# ---------------------------------------------------------------------------
async def test_health_config_flags_missing_model_ref_secret(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr("app.api.ops.weknora_enabled", lambda: True)
    s = get_settings()
    monkeypatch.setattr(s, "weknora_embedding_model_id", "test-embed")  # 隔离该项，专测 ref secret
    monkeypatch.setattr(s, "weknora_model_ref_secret", "")
    r = await client.get("/health/config")
    assert r.status_code == 200
    assert "WEKNORA_MODEL_REF_SECRET" in r.json()["missing_config"]

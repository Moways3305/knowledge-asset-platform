"""PBC-63 external LLM / WeKnora separation and security boundaries."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.main import app
from app.seed.dev_seed import USER_ADMIN_ONLY
from app.services import generation_models, model_connections
from app.services.llm_client import LLMClient
from app.services.weknora_client import get_weknora_client

BASE = "/api/v1/admin/model-connections"
WK_MODELS = "/api/v1/admin/weknora/models"
SECRET = "SECRET-LIKE-external-key"
URL = "https://models.example.test/v1"
RAW_ID = "raw-weknora-model-id"


def _hdr():
    return {"X-Dev-User-Id": str(USER_ADMIN_ONLY)}


class FakeWK:
    def __init__(self) -> None:
        self.models: dict[str, dict] = {}
        self.calls: list[str] = []

    async def list_models(self, *, trace_id=None):
        self.calls.append("list_models")
        return list(self.models.values())

    async def create_model(self, payload, *, trace_id=None):
        self.calls.append("create_model")
        raise AssertionError("external LLM operations must not create WeKnora models")

    async def update_model(self, model_id, payload, *, trace_id=None):
        self.calls.append("update_model")
        raise AssertionError("external LLM operations must not update WeKnora models")


@pytest.fixture
def wk():
    fake = FakeWK()
    app.dependency_overrides[get_weknora_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_weknora_client, None)


def _payload(*, capability_type="chat", enabled=True):
    return {
        "display_name": "外部业务模型",
        "capability_type": capability_type,
        "provider": "openai_compatible",
        "model_name": "business-chat",
        "base_url": URL,
        "api_key": SECRET,
        "enabled": enabled,
    }


async def _create(client, *, enabled=True):
    response = await client.post(BASE, headers=_hdr(), json=_payload(enabled=enabled))
    assert response.status_code == 201, response.text
    return response.json()


async def test_external_llm_create_update_list_and_default_never_call_weknora(client, wk):
    connection = await _create(client)
    assert wk.calls == []

    listed = await client.get(BASE, headers=_hdr())
    assert listed.status_code == 200
    assert listed.json()["items"][0]["available_usages"] == [
        "content_generation",
        "project_qa",
    ]
    assert wk.calls == []

    assigned = await client.put(
        f"{BASE}/usages/current",
        headers=_hdr(),
        json={"external_llm_default_ref": connection["model_ref"]},
    )
    assert assigned.status_code == 200
    assert assigned.json()["external_llm_default"]["model_ref"] == connection["model_ref"]
    assert wk.calls == []

    update = _payload()
    update.pop("base_url")
    update.pop("api_key")
    update["display_name"] = "更新后的外部模型"
    changed = await client.put(
        f"{BASE}/items/{connection['model_ref']}", headers=_hdr(), json=update
    )
    assert changed.status_code == 200
    assert changed.json()["display_name"] == "更新后的外部模型"
    assert wk.calls == []
    for forbidden in (SECRET, URL, RAW_ID, "ciphertext", "api_key", "base_url"):
        assert forbidden not in listed.text + assigned.text + changed.text


async def test_external_llm_rejects_non_chat_and_retired_bridge_assignment_fields(client, wk):
    non_chat = await client.post(BASE, headers=_hdr(), json=_payload(capability_type="embedding"))
    assert non_chat.status_code == 422
    assert non_chat.json()["detail"]["denied_reason"] == "external_llm_chat_required"

    retired = await client.put(
        f"{BASE}/usages/current",
        headers=_hdr(),
        json={"knowledge_chat_ref": "fake-ref"},
    )
    assert retired.status_code == 422
    assert wk.calls == []


async def test_disabled_external_llm_cannot_be_default_or_disable_current_default(client, wk):
    disabled = await _create(client, enabled=False)
    denied = await client.put(
        f"{BASE}/usages/current",
        headers=_hdr(),
        json={"external_llm_default_ref": disabled["model_ref"]},
    )
    assert denied.status_code == 422
    assert denied.json()["detail"]["denied_reason"] == "model_usage_disabled"

    current = await _create(client)
    assert (
        await client.put(
            f"{BASE}/usages/current",
            headers=_hdr(),
            json={"external_llm_default_ref": current["model_ref"]},
        )
    ).status_code == 200
    update = _payload(enabled=False)
    update.pop("base_url")
    update.pop("api_key")
    blocked = await client.put(f"{BASE}/items/{current['model_ref']}", headers=_hdr(), json=update)
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["denied_reason"] == "model_connection_in_use"
    assert wk.calls == []


async def test_external_llm_connection_test_calls_openai_client_not_weknora(
    client, wk, monkeypatch
):
    connection = await _create(client)
    calls: list[str] = []

    async def fake_chat(self, messages, **kwargs):
        calls.append(self.model)
        return "OK"

    monkeypatch.setattr(LLMClient, "chat_completion", fake_chat)
    response = await client.post(
        f"{BASE}/items/{connection['model_ref']}/test", headers=_hdr(), json={}
    )
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert calls == ["business-chat"]
    assert wk.calls == []


async def test_weknora_unavailable_does_not_block_external_llm_save(client):
    response = await client.post(BASE, headers=_hdr(), json=_payload())
    assert response.status_code == 201
    assert response.json()["available_usages"] == ["content_generation", "project_qa"]


async def test_existing_external_and_weknora_models_remain_separate_without_duplication(
    client, wk, monkeypatch
):
    monkeypatch.setattr("app.api.weknora_admin.weknora_enabled", lambda: True)
    wk.models[RAW_ID] = {
        "id": RAW_ID,
        "name": "foundation-chat",
        "type": "KnowledgeQA",
        "source": "remote",
        "status": "active",
        "parameters": {"provider": "foundation"},
    }
    legacy = _payload()
    legacy["make_default"] = False
    legacy.pop("capability_type")
    created = await client.post("/api/v1/admin/generation/models", headers=_hdr(), json=legacy)
    assert created.status_code == 201

    external = await client.get(BASE, headers=_hdr())
    assert external.status_code == 200
    assert external.json()["total"] == 1
    assert external.json()["items"][0]["display_name"] == "外部业务模型"
    assert wk.calls == []

    foundation = await client.get(WK_MODELS, headers=_hdr())
    assert foundation.status_code == 200
    assert foundation.json()["items"][0]["name"] == "foundation-chat"
    assert wk.calls == ["list_models"]
    assert RAW_ID not in foundation.text


async def test_weknora_only_model_is_never_adapted_into_external_llm_list(client, wk):
    wk.models[RAW_ID] = {
        "id": RAW_ID,
        "name": "foundation-only-chat",
        "type": "KnowledgeQA",
        "source": "remote",
        "status": "active",
        "parameters": {"provider": "foundation"},
    }
    response = await client.get(BASE, headers=_hdr())
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert wk.calls == []


async def test_load_failure_is_actionable_and_does_not_echo_raw_database_error(client, monkeypatch):
    async def fail(*args, **kwargs):
        raise SQLAlchemyError(f"database failed {SECRET} {URL}")

    monkeypatch.setattr(model_connections, "list_connections", fail)
    response = await client.get(BASE, headers=_hdr())
    assert response.status_code == 503
    assert response.json()["detail"]["message"] == "模型连接暂时无法加载，请刷新或检查模型连接服务"
    assert SECRET not in response.text
    assert URL not in response.text


async def test_legacy_non_chat_rows_are_preserved_but_hidden_from_external_api(db_session):
    created = await generation_models.create_model(
        db_session,
        display_name="保留的旧嵌入记录",
        provider="legacy",
        model_name="legacy-embedding",
        base_url=URL,
        api_key=SECRET,
        enabled=True,
        make_default=False,
        actor_id=USER_ADMIN_ONLY,
        capability_type="embedding",
    )
    await db_session.commit()

    assert await generation_models.resolve_connection_ref(db_session, created["model_ref"])
    items, warning = await model_connections.list_connections(db_session)
    assert items == []
    assert warning is None

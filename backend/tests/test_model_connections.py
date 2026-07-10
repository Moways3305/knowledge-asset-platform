"""PBC-48 unified model connections, assignments and security boundaries."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.main import app
from app.seed.dev_seed import USER_ADMIN_ONLY
from app.services import model_connections
from app.services.weknora_client import get_weknora_client

BASE = "/api/v1/admin/model-connections"
SECRET = "SECRET-LIKE-unified-key"
URL = "https://models.example.test/v1"
RAW_ID = "raw-weknora-model-id"


def _hdr():
    return {"X-Dev-User-Id": str(USER_ADMIN_ONLY)}


class FakeWK:
    def __init__(self) -> None:
        self.models: dict[str, dict] = {}
        self.counter = 0

    async def list_models(self, *, trace_id=None):
        return list(self.models.values())

    async def create_model(self, payload, *, trace_id=None):
        self.counter += 1
        raw_id = RAW_ID if self.counter == 1 else f"{RAW_ID}-{self.counter}"
        row = {
            "id": raw_id,
            "name": payload["name"],
            "type": payload["type"],
            "source": payload["source"],
            "status": payload.get("status", "active"),
            "parameters": {"provider": payload["parameters"].get("provider")},
        }
        self.models[raw_id] = row
        return row

    async def update_model(self, model_id, payload, *, trace_id=None):
        row = self.models[model_id]
        row.update(name=payload["name"], status=payload.get("status", row["status"]))
        row["parameters"]["provider"] = payload["parameters"].get("provider")
        return row


@pytest.fixture
def wk():
    fake = FakeWK()
    app.dependency_overrides[get_weknora_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_weknora_client, None)


def _payload(capability_type="chat", enabled=True):
    return {
        "display_name": "统一模型连接",
        "capability_type": capability_type,
        "provider": "deepseek",
        "model_name": "deepseek-chat" if capability_type == "chat" else f"test-{capability_type}",
        "base_url": URL,
        "api_key": SECRET,
        "enabled": enabled,
    }


async def _create(client, capability_type="chat", enabled=True):
    response = await client.post(
        BASE,
        headers=_hdr(),
        json=_payload(capability_type=capability_type, enabled=enabled),
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_one_chat_connection_can_serve_content_and_knowledge_chat(client, wk):
    connection = await _create(client)
    response = await client.put(
        f"{BASE}/usages/current",
        headers=_hdr(),
        json={
            "content_generation_ref": connection["model_ref"],
            "knowledge_chat_ref": connection["model_ref"],
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["content_generation"]["model_ref"] == connection["model_ref"]
    assert body["knowledge_chat"]["model_ref"] == connection["model_ref"]
    assert SECRET not in response.text
    assert URL not in response.text
    assert RAW_ID not in response.text


async def test_incompatible_and_disabled_connections_cannot_be_assigned(client, wk):
    embedding = await _create(client, "embedding")
    mismatch = await client.put(
        f"{BASE}/usages/current",
        headers=_hdr(),
        json={"knowledge_chat_ref": embedding["model_ref"]},
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["detail"]["denied_reason"] == "model_usage_type_mismatch"

    disabled = await _create(client, "chat", enabled=False)
    denied = await client.put(
        f"{BASE}/usages/current",
        headers=_hdr(),
        json={"content_generation_ref": disabled["model_ref"]},
    )
    assert denied.status_code == 422
    assert denied.json()["detail"]["denied_reason"] == "model_usage_disabled"


async def test_default_connection_must_be_reassigned_before_disable(client, wk):
    connection = await _create(client)
    assigned = await client.put(
        f"{BASE}/usages/current",
        headers=_hdr(),
        json={"content_generation_ref": connection["model_ref"]},
    )
    assert assigned.status_code == 200, assigned.text
    payload = _payload(enabled=False)
    payload.pop("base_url")
    payload.pop("api_key")
    response = await client.put(
        f"{BASE}/items/{connection['model_ref']}", headers=_hdr(), json=payload
    )
    assert response.status_code == 409
    assert response.json()["detail"]["denied_reason"] == "model_connection_in_use"


async def test_content_usage_remains_configurable_without_weknora(client):
    connection = await _create(client)
    response = await client.put(
        f"{BASE}/usages/current",
        headers=_hdr(),
        json={"content_generation_ref": connection["model_ref"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["content_generation"]["model_ref"] == connection["model_ref"]


async def test_existing_generation_and_weknora_models_are_mapped_without_duplication(client, wk):
    wk.models[RAW_ID] = {
        "id": RAW_ID,
        "name": "deepseek-chat",
        "type": "KnowledgeQA",
        "source": "remote",
        "status": "active",
        "parameters": {"provider": "deepseek"},
    }
    legacy = _payload()
    legacy["make_default"] = False
    legacy.pop("capability_type")
    created = await client.post("/api/v1/admin/generation/models", headers=_hdr(), json=legacy)
    assert created.status_code == 201, created.text

    response = await client.get(BASE, headers=_hdr())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["available_usages"] == [
        "content_generation",
        "knowledge_chat",
    ]
    for forbidden in (SECRET, URL, RAW_ID, "ciphertext", "api_key", "base_url"):
        assert forbidden not in response.text


async def test_legacy_weknora_chat_is_not_offered_for_content_without_platform_credentials(
    client, wk
):
    wk.models[RAW_ID] = {
        "id": RAW_ID,
        "name": "legacy-chat",
        "type": "KnowledgeQA",
        "source": "remote",
        "status": "active",
        "parameters": {"provider": "legacy"},
    }
    response = await client.get(BASE, headers=_hdr())
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["available_usages"] == ["knowledge_chat"]


async def test_load_failure_is_actionable_and_does_not_echo_raw_database_error(
    client, wk, monkeypatch
):
    async def fail(*args, **kwargs):
        raise SQLAlchemyError(f"database failed {SECRET} {URL}")

    monkeypatch.setattr(model_connections, "list_connections", fail)
    response = await client.get(BASE, headers=_hdr())
    assert response.status_code == 503
    assert response.json()["detail"]["message"] == "模型连接暂时无法加载，请刷新或检查模型连接服务"
    assert SECRET not in response.text
    assert URL not in response.text

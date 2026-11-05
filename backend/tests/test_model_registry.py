"""Hermetic onboarding acceptance: no live keys, no production data or external network."""

import uuid

import pytest

from app.main import app
from app.models.model_registry import ProviderConnection
from app.schemas.model_registry import ConnectionInput
from app.seed.dev_seed import USER_ADMIN_ONLY, USER_CONSULTANT
from app.services import generation_models as gm
from app.services import model_probe
from app.services.model_provider_catalog import CATALOG, RegistryError, endpoints_for
from app.services.weknora_client import WeKnoraError, get_weknora_client

BASE = "/api/v1/admin/model-registry"
KEY = "synthetic-registry-key"
HEADERS = {"X-Dev-User-Id": str(USER_ADMIN_ONLY)}


class FakeWK:
    def __init__(self):
        self.models, self.keys = {}, {}
        self.create_calls = 0
        self.fail_key = False
        self.lose_create_response = False

    async def list_models(self, **kw):
        return list(self.models.values())

    async def create_model(self, payload, **kw):
        self.create_calls += 1
        identifier = f"server-only-{self.create_calls}"
        self.models[identifier] = {"id": identifier, **payload}
        if self.lose_create_response:
            self.lose_create_response = False
            raise WeKnoraError("timeout", "DO NOT RETURN raw upstream secret")
        return self.models[identifier]

    async def update_model(self, identifier, payload, **kw):
        self.models[identifier].update(payload)
        return self.models[identifier]

    async def update_model_credentials(self, identifier, *, api_key, **kw):
        if self.fail_key:
            raise WeKnoraError("timeout", "DO NOT RETURN raw upstream secret")
        self.keys[identifier] = api_key
        return {"fields": {"api_key": {"configured": True}}}

    async def get_model_credentials(self, identifier, **kw):
        return {"fields": {"api_key": {"configured": identifier in self.keys}}}

    async def get_model(self, identifier, **kw):
        return self.models[identifier]

    async def check_remote_model(self, **kw):
        return {"available": True}

    test_embedding_model = check_remote_model
    check_rerank_model = check_remote_model


@pytest.fixture
def wk():
    fake = FakeWK()
    app.dependency_overrides[get_weknora_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_weknora_client, None)


@pytest.fixture
def wire(monkeypatch):
    calls = []

    async def post(url, key, payload):
        calls.append((url, key, payload))
        if url.endswith("/embeddings"):
            return {"data": [{"index": 0, "embedding": [0.1] * payload.get("dimensions", 3)}]}
        if "/rerank" in url:
            results = {
                "results": [
                    {"index": 0, "relevance_score": 0.8},
                    {"index": 1, "relevance_score": 0.2},
                ]
            }
            return {"output": results} if "input" in payload else results
        return {"choices": [{"message": {"content": "OK"}}]}

    monkeypatch.setattr(model_probe, "post_probe", post)
    return calls


async def connection(client, provider="siliconflow"):
    payload = {"name": "Synthetic connection", "provider": provider, "api_key": KEY}
    if provider == "aliyun":
        payload["workspace_id"] = "ws-synthetic"
    if provider == "custom":
        payload["endpoints"] = {
            "chat": {"url": "https://model.example.invalid/v1", "protocol": "openai"}
        }
    r = await client.post(BASE + "/connections", headers=HEADERS, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


async def draft(client, conn, cap="chat", usages=None):
    payload = {
        "request_id": str(uuid.uuid4()),
        "connection_id": conn["id"],
        "display_name": "Synthetic " + cap,
        "model_name": "test-" + cap,
        "capability": cap,
        "dimension": 3 if cap == "embedding" else None,
        "usages": usages or (["business", "knowledge"] if cap == "chat" else ["knowledge"]),
    }
    r = await client.post(BASE + "/models", headers=HEADERS, json=payload)
    assert r.status_code == 201, r.text
    return r.json(), payload


async def action(client, model, name):
    r = await client.post(
        f"{BASE}/models/{model['id']}/{name}",
        headers=HEADERS,
        json={"signature": model["signature"]},
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("provider", [p["id"] for p in CATALOG])
async def test_multiple_providers_share_verified_chat_onboarding(client, wk, wire, provider):
    conn = await connection(client, provider)
    model, payload = await draft(client, conn, usages=["business"])
    replay = await client.post(BASE + "/models", headers=HEADERS, json=payload)
    assert replay.json()["id"] == model["id"]
    blocked = await client.post(
        f"{BASE}/models/{model['id']}/sync", headers=HEADERS, json={"signature": model["signature"]}
    )
    assert blocked.status_code == 409
    verified = await action(client, model, "verify")
    assert verified["test_status"] == "verified"
    ready = await action(client, verified, "sync")
    assert ready["bindings"]["business"]["current"] is True
    assert ready["external_ref"] and ready["knowledge_ref"] is None
    await action(client, ready, "sync")
    assert wk.create_calls == 0  # No implicit knowledge binding.
    default = await client.get("/api/v1/admin/model-connections/usages/current", headers=HEADERS)
    assert default.json()["external_llm_default"] is None
    listing = await client.get(BASE, headers=HEADERS)
    for secret in (KEY, "https://", "ciphertext", "server-only-"):
        assert secret not in listing.text


async def test_shared_key_rotation_invalidates_all_models_and_requires_resync(client, wk, wire):
    conn = await connection(client, "aliyun")
    embed, _ = await draft(client, conn, "embedding")
    rerank, _ = await draft(client, conn, "rerank")
    for model in (embed, rerank):
        await action(client, model, "verify")
        ready = await action(client, model, "sync")
        assert ready["bindings"]["knowledge"]["current"]
    assert set(wk.keys.values()) == {KEY}
    updated = await client.put(
        f"{BASE}/connections/{conn['id']}",
        headers=HEADERS,
        json={
            "name": conn["name"],
            "provider": conn["provider"],
            "api_key": "rotated-synthetic-key",
            "expected_version": 1,
        },
    )
    assert updated.status_code == 200
    assert updated.json()["model_count"] == 2
    listing = (await client.get(BASE, headers=HEADERS)).json()
    assert all(
        m["test_status"] == "untested" and not m["bindings"]["knowledge"]["current"]
        for m in listing["models"]
    )
    stale = await client.post(
        f"{BASE}/models/{embed['id']}/sync", headers=HEADERS, json={"signature": embed["signature"]}
    )
    assert stale.status_code == 409
    for m in listing["models"]:
        await action(client, m, "verify")
        await action(client, m, "sync")
    assert wk.create_calls == 2
    assert set(wk.keys.values()) == {"rotated-synthetic-key"}
    assert any("/compatible-mode/v1/embeddings" in url for url, _, _ in wire)
    assert any("/services/rerank/" in url and "input" in p for url, _, p in wire)


@pytest.mark.parametrize("lost_response", [False, True])
async def test_partial_sync_is_resumable_without_duplicate_remote_creation(
    client, wk, wire, lost_response
):
    model, _ = await draft(client, await connection(client))
    await action(client, model, "verify")
    wk.fail_key = not lost_response
    wk.lose_create_response = lost_response
    failed = await action(client, model, "sync")
    assert failed["bindings"]["business"]["current"]
    assert failed["bindings"]["knowledge"]["status"] == "failed"
    assert "raw upstream" not in str(failed)
    wk.fail_key = False
    ready = await action(client, model, "sync")
    assert ready["bindings"]["knowledge"]["current"]
    assert wk.create_calls == 1


async def test_ambiguous_create_never_repeats_without_authoritative_match(client, wk, wire):
    model, _ = await draft(client, await connection(client), usages=["knowledge"])
    await action(client, model, "verify")
    wk.lose_create_response = True
    await action(client, model, "sync")
    wk.models.clear()
    retry = await action(client, model, "sync")
    assert retry["bindings"]["knowledge"]["error_code"] == "creation_unconfirmed"
    assert wk.create_calls == 1


async def test_dimension_and_rerank_validation_are_not_http_status_only(client, wk, monkeypatch):
    conn = await connection(client)
    embed, _ = await draft(client, conn, "embedding")

    async def wrong_dimension(*args):
        return {"data": [{"embedding": [1, 2]}]}

    monkeypatch.setattr(model_probe, "post_probe", wrong_dimension)
    result = await action(client, embed, "verify")
    assert result["test_code"] == "dimension_mismatch"
    rank, _ = await draft(client, conn, "rerank")

    async def wrong_indices(*args):
        return {
            "results": [{"index": 0, "relevance_score": 1}, {"index": 0, "relevance_score": 0.5}]
        }

    monkeypatch.setattr(model_probe, "post_probe", wrong_indices)
    result = await action(client, rank, "verify")
    assert result["test_code"] == "invalid_response"
    assert wk.create_calls == 0


async def test_managed_runtime_edits_and_bound_embedding_changes_are_rejected(client, wk, wire):
    conn = await connection(client)
    model, payload = await draft(client, conn, "embedding")
    await action(client, model, "verify")
    ready = await action(client, model, "sync")
    payload.update(dimension=4, expected_version=1)
    edited = await client.put(f"{BASE}/models/{model['id']}", headers=HEADERS, json=payload)
    assert edited.status_code == 409
    # Admin API still requires configured WK before mutating; guard itself is independent.
    deleted = await client.delete(
        f"/api/v1/admin/weknora/models/{ready['knowledge_ref']}", headers=HEADERS
    )
    assert deleted.status_code == 409


async def test_metadata_and_credentials_encrypted_and_validation_safe(client, db_session):
    conn = await connection(client)
    row = await db_session.get(ProviderConnection, uuid.UUID(conn["id"]))
    assert KEY not in row.key_ciphertext and "https://" not in row.config_ciphertext
    assert gm._decrypt(row.key_ciphertext) == KEY
    invalid = await client.post(
        BASE + "/connections",
        headers=HEADERS,
        json={"name": "x", "provider": "custom", "api_key": {"secret": KEY}},
    )
    assert invalid.status_code == 422 and KEY not in invalid.text
    denied = await client.get(BASE, headers={"X-Dev-User-Id": str(USER_CONSULTANT)})
    assert denied.status_code == 403


async def test_busy_connection_and_stale_results_cannot_overwrite_new_config(
    client, wk, monkeypatch, sessionmaker_fixture
):
    conn = await connection(client)
    model, _ = await draft(client, conn)

    async def late(*args):
        denied = await client.put(
            f"{BASE}/connections/{conn['id']}",
            headers=HEADERS,
            json={
                "name": "edit",
                "provider": "siliconflow",
                "api_key": "other-key",
                "expected_version": 1,
            },
        )
        assert denied.status_code == 409
        # Simulate a newer committed revision after lease recovery / another worker.
        async with sessionmaker_fixture() as s:
            row = await s.get(ProviderConnection, uuid.UUID(conn["id"]))
            row.config_version += 1
            await s.commit()
        return None

    monkeypatch.setattr(model_probe, "probe", late)
    result = await client.post(
        f"{BASE}/models/{model['id']}/verify",
        headers=HEADERS,
        json={"signature": model["signature"]},
    )
    assert result.status_code == 409
    listing = (await client.get(BASE, headers=HEADERS)).json()
    assert listing["models"][0]["test_status"] == "untested"


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (403, {"code": "Endpoint.AccessDenied"}, "workspace_denied"),
        (400, {"code": "Arrearage"}, "account_arrears"),
        (403, {}, "access_denied"),
        (429, {}, "rate_limited"),
    ],
)
def test_provider_error_classification_requires_evidence(status, body, expected):
    assert model_probe.error_code(status, body) == expected


def test_templates_reject_wrong_protocol_and_credentials_in_urls():
    with pytest.raises(RegistryError):
        endpoints_for(
            ConnectionInput(
                name="test",
                provider="custom",
                endpoints={
                    "chat": {"protocol": "openai", "url": "https://user:password@example.com/v1"}
                },
            )
        )
    with pytest.raises(RegistryError):
        endpoints_for(
            ConnectionInput(
                name="test",
                provider="deepseek",
                endpoints={"rerank": {"protocol": "rerank", "url": "https://example.com/rerank"}},
            )
        )


async def test_incomplete_knowledge_binding_cannot_be_selected(client, wk, wire, db_session):
    from app.services import weknora_models as wm
    from app.services.model_registry_availability import (
        filter_knowledge_options,
        filter_knowledge_runtime,
    )

    model, _ = await draft(client, await connection(client), usages=["knowledge"])
    await action(client, model, "verify")
    wk.fail_key = True
    await action(client, model, "sync")
    assert await filter_knowledge_runtime(db_session, list(wk.models.values())) == []
    safe = [wm._to_model_out(raw) for raw in wk.models.values()]
    assert await filter_knowledge_options(db_session, safe) == []
    wk.fail_key = False
    await action(client, model, "sync")
    assert len(await filter_knowledge_runtime(db_session, list(wk.models.values()))) == 1
    options = await filter_knowledge_options(db_session, safe)
    assert len(options) == 1 and options[0].description is None


async def test_connection_create_request_is_idempotent(client):
    payload = {
        "request_id": str(uuid.uuid4()),
        "name": "once",
        "provider": "deepseek",
        "api_key": KEY,
    }
    first = await client.post(BASE + "/connections", headers=HEADERS, json=payload)
    second = await client.post(BASE + "/connections", headers=HEADERS, json=payload)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert len((await client.get(BASE, headers=HEADERS)).json()["connections"]) == 1
    payload["api_key"] = "different-key"
    conflict = await client.post(BASE + "/connections", headers=HEADERS, json=payload)
    assert conflict.status_code == 409 and "different-key" not in conflict.text

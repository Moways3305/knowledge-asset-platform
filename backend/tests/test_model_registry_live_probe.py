"""Preflight the live runner against real KAP routes, with synthetic identity/provider adapters."""

import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from test_model_registry import wire, wk  # noqa: F401

from app.core.config import get_settings
from app.seed.dev_seed import USER_ADMIN_ONLY
from app.services.llm_client import LLMClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import weknora_model_registry_probe as probe  # noqa: E402


@pytest.mark.parametrize("ui_only", [False, True])
async def test_live_runner_api_workflow(client, monkeypatch, db_session, wk, wire, ui_only):  # noqa: F811
    # Login/TLS have separate real HTTPS acceptance coverage; here use the existing
    # test identity to validate every registry/default/runtime route in the new probe.
    client.headers["X-Dev-User-Id"] = str(USER_ADMIN_ONLY)
    monkeypatch.setattr(get_settings(), "weknora_base_url", "http://synthetic.invalid")
    monkeypatch.setattr(get_settings(), "weknora_api_key", "synthetic-weknora")

    class ClientAdapter:
        headers = {}
        cookies = {"kap_session": "synthetic-session"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, path):
            if path.endswith("/me"):
                return httpx.Response(401)
            return httpx.Response(200, json={"csrf_token": "synthetic-csrf"})

        async def post(self, path, **kwargs):
            assert path.endswith("/login")
            return httpx.Response(200, headers={"set-cookie": "kap_session=synthetic; Secure"})

        async def request(self, method, path, **kwargs):
            return await client.request(method, path, **kwargs)

    async def synthetic_completion(*args, **kwargs):
        return "OK"

    monkeypatch.setattr(probe.httpx, "AsyncClient", lambda **kwargs: ClientAdapter())
    monkeypatch.setattr(probe.ssl, "create_default_context", lambda **kwargs: None)
    monkeypatch.setattr(LLMClient, "chat_completion", synthetic_completion)
    probe.REPORT["checks"] = []
    models = {
        slot: {
            "name": "synthetic-" + slot,
            "key": "synthetic-deepseek" if slot == "chat" else "synthetic-shared",
            "url": "https://api.deepseek.com/v1",
        }
        for slot in ("embedding", "rerank", "chat")
    }
    await probe.exercise(
        {"email": "synthetic@example.invalid", "password": "synthetic"},
        models,
        "ws-fixture",
        "synthetic-cert",
        SimpleNamespace(poll=lambda: None),
        ui_only=ui_only,
    )
    assert all(c["passed"] for c in probe.REPORT["checks"])
    if ui_only:
        assert wk.create_calls == 0
        assert len(wire) == 0
        inventory = (await client.get(probe.BASE)).json()
        assert len(inventory["connections"]) == 2
        assert inventory["models"] == []
        return
    assert wk.create_calls == 3
    assert len(wire) == 3
    assert [c["case"] for c in probe.REPORT["checks"]].count("runtime_binding_verified") == 4

    # Verified custom model identifiers must remain selectable through legacy KB
    # defaults and runtime resolution, not merely appear in the registry table.
    from app.services.weknora_model_selection import resolve_models_for_kb

    inventory = (await client.get(probe.BASE)).json()
    refs = {m["capability"] + "_model_ref": m["knowledge_ref"] for m in inventory["models"]}
    saved = await client.put("/api/v1/admin/weknora/default-models", json=refs)
    assert saved.status_code == 200
    selected = await resolve_models_for_kb(
        db_session, wk, embedding_model_ref=None, rerank_model_ref=None, trace_id=None
    )
    assert selected.chat.model_name == "synthetic-chat"
    assert selected.embedding.model_name == "synthetic-embedding"
    wk.models[selected.chat_model_id]["name"] = "unverified-remote-replacement"
    options = (await client.get("/api/v1/admin/weknora/models")).json()["items"]
    assert len(options) == 2

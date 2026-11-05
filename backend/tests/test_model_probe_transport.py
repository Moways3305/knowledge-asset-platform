"""Network guard tests without DNS queries, vendor calls or real credentials."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from app.services import model_probe
from app.services.model_provider_catalog import RegistryError


def network(monkeypatch, *, addresses, response, allowed="", proxy=""):
    calls = []

    async def resolve(*args, **kwargs):
        return [(2, 1, 6, "", (address, 443)) for address in addresses]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr(
        model_probe,
        "get_settings",
        lambda: SimpleNamespace(
            model_registry_private_hosts=allowed, model_registry_proxy_url=proxy
        ),
    )
    original = httpx.AsyncClient

    def handle(request):
        calls.append(request)
        return response

    def client(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        assert (kwargs.pop("proxy", None) or "") == proxy
        return original(transport=httpx.MockTransport(handle), **kwargs)

    monkeypatch.setattr(model_probe.httpx, "AsyncClient", client)
    return calls


@pytest.mark.parametrize("addresses", [["127.0.0.1"], ["8.8.8.8", "10.0.0.1"], ["::1"]])
async def test_private_or_mixed_dns_results_are_blocked(monkeypatch, addresses):
    calls = network(monkeypatch, addresses=addresses, response=httpx.Response(200, json={}))
    with pytest.raises(RegistryError, match="endpoint_blocked"):
        await model_probe.post_probe("https://models.example.test/v1", "synthetic", {})
    assert calls == []


async def test_public_request_pins_ip_and_preserves_tls_name(monkeypatch):
    calls = network(
        monkeypatch, addresses=["8.8.8.8"], response=httpx.Response(200, json={"ok": True})
    )
    assert await model_probe.post_probe("https://models.example.test/v1", "synthetic", {}) == {
        "ok": True
    }
    assert calls[0].url.host == "8.8.8.8"
    assert calls[0].headers["Host"] == "models.example.test"
    assert calls[0].extensions["sni_hostname"] == "models.example.test"


async def test_explicit_gateway_preserves_hostname_for_connect_allowlist(monkeypatch):
    calls = network(
        monkeypatch,
        addresses=["8.8.8.8"],
        response=httpx.Response(200, json={}),
        proxy="http://approved-gateway:18080",
    )
    await model_probe.post_probe("https://models.example.test/v1", "synthetic", {})
    assert calls[0].url.host == calls[0].headers["Host"] == "models.example.test"


async def test_gateway_mode_still_blocks_private_target_dns(monkeypatch):
    calls = network(
        monkeypatch,
        addresses=["10.0.0.1"],
        response=httpx.Response(200, json={}),
        proxy="http://approved-gateway:18080",
    )
    with pytest.raises(RegistryError, match="endpoint_blocked"):
        await model_probe.post_probe("https://models.example.test/v1", "synthetic", {})
    assert not calls


async def test_redirect_does_not_forward_credentials(monkeypatch):
    calls = network(
        monkeypatch,
        addresses=["8.8.8.8"],
        response=httpx.Response(302, headers={"Location": "http://127.0.0.1/private"}),
    )
    with pytest.raises(RegistryError, match="provider_error"):
        await model_probe.post_probe("https://models.example.test/v1", "synthetic", {})
    assert len(calls) == 1


async def test_large_response_is_bounded(monkeypatch):
    network(
        monkeypatch, addresses=["8.8.8.8"], response=httpx.Response(200, content=b"x" * 2_000_001)
    )
    with pytest.raises(RegistryError, match="invalid_response"):
        await model_probe.post_probe("https://models.example.test/v1", "synthetic", {})


async def test_explicit_private_gateway_and_public_https_requirement(monkeypatch):
    calls = network(
        monkeypatch,
        addresses=["127.0.0.1"],
        response=httpx.Response(200, json={}),
        allowed="approved.test",
    )
    assert await model_probe.post_probe("http://approved.test/v1", "synthetic", {}) == {}
    with pytest.raises(RegistryError, match="https_required"):
        await model_probe.post_probe("http://unapproved.test/v1", "synthetic", {})
    assert len(calls) == 1


async def test_malformed_embedding_returns_safe_diagnostic(monkeypatch):
    async def malformed(*args):
        return {"data": [42]}

    monkeypatch.setattr(model_probe, "post_probe", malformed)
    with pytest.raises(RegistryError, match="invalid_response"):
        await model_probe.probe(
            {"url": "https://models.example.test/v1", "protocol": "openai"},
            "synthetic",
            "embed",
            "embedding",
            3,
        )


@pytest.mark.parametrize("body", [[], ["private-provider-detail"], None, "not-an-object"])
async def test_non_object_response_returns_safe_diagnostic(monkeypatch, body):
    network(
        monkeypatch,
        addresses=["8.8.8.8"],
        response=httpx.Response(200, content=json.dumps(body)),
    )
    with pytest.raises(RegistryError, match="invalid_response") as caught:
        await model_probe.post_probe("https://models.example.test/v1", "synthetic", {})
    assert "private-provider-detail" not in str(caught.value)

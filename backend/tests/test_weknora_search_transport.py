"""Synthetic transport failures must not broaden retrieval scopes or leak URLs."""

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest

from app.services import weknora_client as module
from app.services.weknora_client import WeKnoraClient, WeKnoraError


def install_transport(monkeypatch, stage, error, *, persistent=False):
    calls = []
    failures = []
    target = {
        "scope": "/api/v1/knowledge/batch",
        "search": "/api/v1/knowledge-search",
        "scoped_search": "/api/v1/knowledge-search",
        "hybrid": "/api/v1/knowledge-bases/kb-safe/hybrid-search",
    }[stage]

    def handle(request):
        calls.append(request)
        if request.url.path == target and (persistent or not failures):
            failures.append(request)
            raise error("SECRET upstream URL and sk-synthetic", request=request)
        if request.url.path.endswith("/knowledge/batch"):
            return httpx.Response(
                200,
                json={"data": [{"id": "doc-safe", "knowledge_base_id": "kb-safe"}]},
            )
        return httpx.Response(
            200, json={"data": [{"knowledge_id": "doc-safe", "content": "synthetic"}]}
        )

    @asynccontextmanager
    async def pool(*, timeout):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            yield client

    monkeypatch.setattr(module, "pooled_http_client", pool)
    return WeKnoraClient(base_url="https://upstream.invalid", api_key="sk-synthetic"), calls, target


async def retrieve(client, stage):
    if stage == "hybrid":
        return await client.hybrid_search(query="synthetic", kb_id="kb-safe")
    return await client.search(
        query="synthetic",
        kb_ids=["kb-safe"],
        knowledge_ids=["doc-safe"] if stage in {"scope", "scoped_search"} else None,
        trace_id="synthetic-trace",
    )


@pytest.mark.parametrize("stage", ["scope", "search", "scoped_search", "hybrid"])
@pytest.mark.parametrize("error", [httpx.ReadError, httpx.ConnectError, httpx.RemoteProtocolError])
async def test_transient_read_only_transport_failure_retries_same_scope(monkeypatch, stage, error):
    client, calls, target = install_transport(monkeypatch, stage, error)
    result = await retrieve(client, stage)
    assert result[0]["knowledge_id"] == "doc-safe"
    attempts = [r for r in calls if r.url.path == target]
    assert len(attempts) == 2
    assert attempts[0].method == attempts[1].method
    assert attempts[0].url == attempts[1].url
    assert attempts[0].content == attempts[1].content
    assert attempts[0].headers == attempts[1].headers


@pytest.mark.parametrize("stage", ["scope", "search", "scoped_search", "hybrid"])
@pytest.mark.parametrize(
    "error,attempts", [(httpx.ReadError, 2), (httpx.RemoteProtocolError, 2), (httpx.ReadTimeout, 1)]
)
async def test_transport_failure_is_bounded_and_sanitized(
    monkeypatch, caplog, stage, error, attempts
):
    client, calls, target = install_transport(monkeypatch, stage, error, persistent=True)
    with pytest.raises(WeKnoraError) as caught:
        await retrieve(client, stage)
    assert caught.value.code == "weknora_network_error"
    assert "SECRET" not in str(caught.value) + caplog.text
    assert "sk-synthetic" not in str(caught.value) + caplog.text
    assert len([r for r in calls if r.url.path == target]) == attempts
    if stage == "scope":
        assert all(r.url.path.endswith("/knowledge/batch") for r in calls)


async def test_cancel_during_retry_delay_does_not_send_again(monkeypatch):
    client, calls, _ = install_transport(monkeypatch, "search", httpx.ReadError)
    task = asyncio.create_task(retrieve(client, "search"))
    while not calls and not task.done():
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(calls) == 1


@pytest.mark.parametrize("method", ["delete", "create"])
async def test_write_operations_are_not_replayed(monkeypatch, method):
    calls = []

    def handle(request):
        calls.append(request)
        raise httpx.ReadError("synthetic disconnect", request=request)

    @asynccontextmanager
    async def pool(*, timeout):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            yield client

    monkeypatch.setattr(module, "pooled_http_client", pool)
    client = WeKnoraClient(base_url="https://upstream.invalid", api_key="sk-synthetic")
    with pytest.raises(httpx.ReadError):
        if method == "delete":
            await client.delete_knowledge("doc-safe")
        else:
            await client.create_kb(name="synthetic", embedding_model_id="synthetic")
    assert len(calls) == 1

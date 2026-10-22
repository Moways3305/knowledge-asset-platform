"""Wire-contract regressions against WeKnora v0.8.3, not live-server tests.

Reference: Tencent/WeKnora 3e22822c1d2397be730c458c7539d0eb8c113a24
internal/handler/session/types.go; internal/types/search.go; routes_knowledge.go.
Fixtures contain synthetic IDs/content only. No external network or model calls.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import httpx
import pytest

import app.services.weknora_client as module
from app.services.weknora_client import WeKnoraClient, WeKnoraError


@pytest.fixture
def wire(monkeypatch):
    requests = []
    response = {
        "success": True,
        "data": [{"knowledge_id": "doc-fixture", "content": "synthetic", "score": 0.8}],
        "meta": {"diagnostics": {"model_id": "private-fixture"}},
    }
    status = [200]

    def handle(request):
        requests.append(request)
        return httpx.Response(status[0], json=response)

    @asynccontextmanager
    async def pool(*, timeout):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            yield client

    monkeypatch.setattr(module, "pooled_http_client", pool)
    client = WeKnoraClient(base_url="https://weknora.invalid", api_key="sk-synthetic-test")
    return client, requests, response, status


@pytest.mark.parametrize("count", [1, 20, 100])
@pytest.mark.parametrize("knowledge_ids", [None, ["doc-a", "doc-b"]])
async def test_search_083_wire_count_and_scopes(wire, count, knowledge_ids):
    client, requests, _, _ = wire
    result = await client.search(
        query="generic query",
        kb_ids=["kb-a", "kb-b"],
        knowledge_ids=knowledge_ids,
        top_k=count,
        trace_id="trace-fixture",
    )
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/api/v1/knowledge-search"
    expected = {
        "query": "generic query",
        "knowledge_base_ids": ["kb-a", "kb-b"],
        "match_count": count,
    }
    if knowledge_ids is not None:
        expected["knowledge_ids"] = knowledge_ids
    assert json.loads(request.content) == expected
    assert request.headers["X-Request-ID"] == "trace-fixture"
    assert request.headers["X-API-Key"] == "sk-synthetic-test"
    assert result[0]["knowledge_id"] == "doc-fixture"
    assert "private-fixture" not in json.dumps(result)


@pytest.mark.parametrize(
    "query,kbs,docs", [("  ", ["kb"], None), ("q", [], None), ("q", ["kb"], [])]
)
async def test_explicit_empty_scope_never_reaches_upstream(wire, query, kbs, docs):
    client, requests, _, _ = wire
    assert await client.search(query=query, kb_ids=kbs, knowledge_ids=docs) == []
    assert requests == []


@pytest.mark.parametrize("threshold", [None, 0.0, 0.5])
async def test_hybrid_wire_uses_supported_post_and_parameter_names(wire, threshold):
    client, requests, _, _ = wire
    await client.hybrid_search(
        kb_id="kb-a",
        query="generic query",
        top_k=100,
        vector_threshold=threshold,
        keyword_threshold=threshold,
    )
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/api/v1/knowledge-bases/kb-a/hybrid-search"
    expected = {"query_text": "generic query", "match_count": 100}
    if threshold is not None:
        expected.update(vector_threshold=threshold, keyword_threshold=threshold)
    assert json.loads(request.content) == expected


@pytest.mark.parametrize("method", ["search", "hybrid_search"])
@pytest.mark.parametrize("status_code", [400, 403, 404, 500])
async def test_rejected_requests_do_not_retry_with_broader_scope(wire, method, status_code):
    client, requests, response, status = wire
    status[0] = status_code
    response.clear()
    response.update(success=False, error={"code": "rejected", "message": "rejected"})
    with pytest.raises(WeKnoraError):
        if method == "search":
            await client.search(query="q", kb_ids=["kb"], knowledge_ids=["doc"])
        else:
            await client.hybrid_search(query="q", kb_id="kb")
    assert len(requests) == 1


@pytest.mark.parametrize("query,kb", [(" ", "kb"), ("q", "")])
async def test_empty_hybrid_query_or_scope_is_not_sent(wire, query, kb):
    client, requests, _, _ = wire
    assert await client.hybrid_search(query=query, kb_id=kb) == []
    assert requests == []


async def test_search_keeps_more_than_legacy_default_ten_candidates(wire):
    client, _, response, _ = wire
    response["data"] = [
        {"knowledge_id": f"doc-{index}", "content": "synthetic", "seq": index}
        for index in range(100)
    ]
    result = await client.search(query="generic query", kb_ids=["kb"], top_k=100)
    assert len(result) == 100
    assert result[-1]["knowledge_id"] == "doc-99"


async def test_legacy_wrapped_response_is_still_normalized(wire):
    client, _, response, _ = wire
    response["data"] = {"results": response["data"]}
    result = await client.search(query="generic query", kb_ids=["kb"])
    assert len(result) == 1
    assert result[0]["knowledge_id"] == "doc-fixture"

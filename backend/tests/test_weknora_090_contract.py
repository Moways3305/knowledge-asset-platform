"""Synthetic wire regressions for v0.9.0 asynchronous deletion.

Source: Tencent/WeKnora f17ee8a8da901bd658a4cb25f40b5fd41adbfdd7,
internal/handler/knowledge.go DeleteKnowledge. Not a live-container test.
"""

from contextlib import asynccontextmanager

import httpx
import pytest

import app.services.weknora_client as module
from app.services.weknora_client import WeKnoraClient, WeKnoraError


def client_for(monkeypatch, responses, *, timeout=2):
    requests = []

    def handle(request):
        requests.append(request)
        status, payload = responses.pop(0)
        return httpx.Response(status, json=payload)

    @asynccontextmanager
    async def pool(*, timeout):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            yield client

    monkeypatch.setattr(module, "pooled_http_client", pool)
    return WeKnoraClient(
        base_url="https://fixture.invalid", api_key="sk-fixture", timeout=timeout
    ), requests


async def reparse(client):
    return await client.reparse_knowledge(
        kb_id="kb-fixture",
        knowledge_id="old-doc",
        content=b"canonical fixture",
        file_name="fixture.canonical.md",
        mime="text/markdown",
        trace_id="trace-fixture",
    )


async def test_reparse_waits_for_async_delete_before_upload(monkeypatch):
    client, requests = client_for(
        monkeypatch,
        [
            (200, {"success": True, "data": {"task_id": "delete-task"}}),
            (200, {"success": True, "data": {"id": "old-doc", "parse_status": "deleting"}}),
            (404, {"success": False}),
            (200, {"success": True, "data": {"id": "new-doc", "parse_status": "pending"}}),
        ],
    )
    result = await reparse(client)
    assert [r.method for r in requests] == ["DELETE", "GET", "GET", "POST"]
    assert result == {"id": "new-doc", "parse_status": "pending"}
    assert b"canonical fixture" in requests[-1].content
    assert requests[-1].url.path == "/api/v1/knowledge-bases/kb-fixture/knowledge/file"
    assert all(r.headers["X-Request-ID"] == "trace-fixture" for r in requests)


@pytest.mark.parametrize("status", [401, 403, 500])
async def test_reparse_does_not_upload_after_delete_failure(monkeypatch, status):
    client, requests = client_for(monkeypatch, [(status, {"success": False})])
    with pytest.raises(WeKnoraError):
        await reparse(client)
    assert [r.method for r in requests] == ["DELETE"]


async def test_reparse_delete_timeout_never_uploads(monkeypatch):
    client, requests = client_for(
        monkeypatch,
        [
            (200, {"success": True, "data": {"task_id": "delete-task"}}),
            (200, {"success": True, "data": {"id": "old-doc"}}),
        ],
        timeout=0.01,
    )
    with pytest.raises(WeKnoraError) as exc:
        await reparse(client)
    assert exc.value.code == "weknora_delete_pending"
    assert all(r.method != "POST" for r in requests)


async def test_reparse_duplicate_does_not_report_completion(monkeypatch):
    client, requests = client_for(
        monkeypatch,
        [
            (200, {"success": True}),
            (404, {"success": False}),
            (409, {"success": False, "code": "duplicate_file", "data": {"id": "competing-doc"}}),
        ],
    )
    with pytest.raises(WeKnoraError) as exc:
        await reparse(client)
    assert exc.value.code == "weknora_reparse_duplicate"
    assert len(requests) == 3


async def test_reparse_supports_synchronous_old_provider_and_missing_doc(monkeypatch):
    client, requests = client_for(
        monkeypatch,
        [
            (404, {"success": False}),
            (404, {"success": False}),
            (200, {"success": True, "data": {"id": "new-doc", "parse_status": "processing"}}),
        ],
    )
    assert (await reparse(client))["id"] == "new-doc"
    assert [r.method for r in requests] == ["DELETE", "GET", "POST"]

"""Admission happens before dependencies; cancelled work must release its resources."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core import search_load
from app.core.search_load import SearchLoadGuard

PATHS = [
    "/api/v1/knowledge/search",
    "/api/v1/agent-gateway/tools/knowledge-search",
    "/api/v1/projects/project-1/qa",
]


class Connection:
    def __init__(self, path=PATHS[0]):
        self.scope = {"type": "http", "method": "POST", "path": path, "headers": []}
        self.incoming = asyncio.Queue()
        self.incoming.put_nowait({"type": "http.request", "body": b"{}", "more_body": False})
        self.sent = []

    async def send(self, message):
        self.sent.append(message)

    async def run(self, app):
        await app(self.scope, self.incoming.get, self.send)

    def disconnect(self):
        self.incoming.put_nowait({"type": "http.disconnect"})

    @property
    def status(self):
        return next(
            message["status"] for message in self.sent if message["type"] == "http.response.start"
        )


@pytest.fixture(autouse=True)
def limits(monkeypatch):
    settings = SimpleNamespace(search_concurrency_per_worker=1, search_timeout_seconds=2)
    monkeypatch.setattr(search_load, "get_settings", lambda: settings)
    return settings


@pytest.mark.parametrize("held_path", PATHS)
async def test_shared_admission_rejects_without_invoking_app_and_exempts_light_routes(held_path):
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def app(scope, receive, send):
        calls.append(scope["path"])
        if scope["path"] == held_path:
            entered.set()
            await release.wait()
        await JSONResponse({"ok": True})(scope, receive, send)

    guard = SearchLoadGuard(app)
    held = asyncio.create_task(Connection(held_path).run(guard))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        for path in PATHS:
            request = Connection(path)
            await asyncio.wait_for(request.run(guard), 0.5)
            assert request.status == 503
            assert dict(request.sent[0]["headers"])[b"retry-after"] == b"2"
            assert b"x-trace-id" in dict(request.sent[0]["headers"])
            assert json.loads(request.sent[1]["body"])["detail"]["denied_reason"] == "search_busy"
        assert calls == [held_path]
        for path in ("/api/v1/auth/login", "/api/v1/knowledge", "/api/v1/ingest/upload"):
            request = Connection(path)
            await request.run(guard)
            assert request.status == 200
    finally:
        release.set()
        await held
    request = Connection(PATHS[1])
    await request.run(guard)
    assert request.status == 200


@pytest.mark.parametrize("trigger", ["disconnect", "timeout", "caller_cancel"])
async def test_cancellation_waits_for_cleanup_before_readmitting(trigger, limits):
    entered, cleaning, cleaned, release = (asyncio.Event() for _ in range(4))
    limits.search_timeout_seconds = 0.03 if trigger == "timeout" else 2

    async def app(scope, receive, send):
        await receive()
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await release.wait()
            cleaned.set()

    guard = SearchLoadGuard(app)
    request = Connection()
    task = asyncio.create_task(request.run(guard))
    await asyncio.wait_for(entered.wait(), 1)
    if trigger == "disconnect":
        request.disconnect()
    elif trigger == "caller_cancel":
        task.cancel()
    await asyncio.wait_for(cleaning.wait(), 1)
    refused = Connection(PATHS[2])
    await refused.run(guard)
    assert refused.status == 503
    assert not cleaned.is_set()
    release.set()
    if trigger == "caller_cancel":
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        await asyncio.wait_for(task, 1)
    assert cleaned.is_set()
    assert not guard._active
    if trigger == "timeout":
        assert request.status == 504
        assert json.loads(request.sent[1]["body"])["detail"]["denied_reason"] == "search_timeout"
    elif trigger == "disconnect":
        assert request.status == 499
    else:
        assert not request.sent


async def test_disconnect_cancels_nested_base_middleware_and_dependency_cleanup():
    entered, cleaned = asyncio.Event(), asyncio.Event()

    async def app(scope, receive, send):
        await receive()
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            # Real async cleanup, not just a synchronous flag in a finally block.
            await asyncio.sleep(0)
            cleaned.set()

    async def dispatch(request, call_next):
        return await call_next(request)

    guard = SearchLoadGuard(app)
    nested = BaseHTTPMiddleware(BaseHTTPMiddleware(guard, dispatch=dispatch), dispatch=dispatch)
    request = Connection()
    task = asyncio.create_task(request.run(nested))
    await asyncio.wait_for(entered.wait(), 1)
    request.disconnect()
    await asyncio.wait_for(task, 1)
    assert cleaned.is_set()
    assert not guard._active


async def test_post_response_disconnect_does_not_cancel_successful_cleanup():
    cleaned = asyncio.Event()
    request = Connection()

    async def app(scope, receive, send):
        await receive()
        await JSONResponse({"ok": True})(scope, receive, send)
        request.disconnect()  # ASGITransport behavior after sending a response.
        await asyncio.sleep(0.02)
        cleaned.set()

    await request.run(SearchLoadGuard(app))
    assert request.status == 200
    assert cleaned.is_set()


@pytest.mark.parametrize("failure", ["receive", "operation"])
async def test_failures_release_admission_and_propagate(failure):
    async def app(scope, receive, send):
        await receive()
        if failure == "operation":
            raise ValueError("synthetic failure")
        await asyncio.Event().wait()

    async def receive():
        raise ValueError("synthetic receive failure")

    request = Connection()
    guard = SearchLoadGuard(app)
    with pytest.raises(ValueError, match="synthetic"):
        await asyncio.wait_for(
            guard(
                request.scope,
                receive if failure == "receive" else request.incoming.get,
                request.send,
            ),
            1,
        )
    assert not guard._active


async def test_started_response_is_not_replaced_with_timeout(limits):
    limits.search_timeout_seconds = 0.01

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await asyncio.sleep(0.03)
        await send({"type": "http.response.body", "body": b"ok"})

    request = Connection()
    await request.run(SearchLoadGuard(app))
    assert [message.get("status") for message in request.sent] == [200, None]


async def test_app_failure_after_headers_does_not_send_second_status():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await asyncio.sleep(0)
        raise ValueError("synthetic failure")

    request = Connection()
    guard = SearchLoadGuard(app)
    with pytest.raises(ValueError, match="synthetic"):
        await request.run(guard)
    assert [message.get("status") for message in request.sent] == [200]
    assert not guard._active

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.services import http_pool
from app.services.http_pool import outbound_http_pool, pooled_http_client


async def test_pool_reuses_and_closes_clients_without_cross_request_credentials(monkeypatch):
    requests = []

    async def respond(request):
        requests.append(request)
        return httpx.Response(200, headers={"set-cookie": "secret=first; Path=/"}, json={})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    async with outbound_http_pool():
        async with pooled_http_client(timeout=30) as first:
            await first.get("https://upstream.test/", headers={"Authorization": "Bearer first"})
        assert not first.is_closed
        async with pooled_http_client(timeout=30) as second:
            assert first is second
            await second.get("https://upstream.test/", headers={"Authorization": "Bearer second"})
        assert requests[1].headers["authorization"] == "Bearer second"
        assert "cookie" not in requests[1].headers
        assert not second.cookies
    assert first.is_closed
    assert asyncio.get_running_loop() not in http_pool._pools


async def test_nested_owners_and_timeout_isolation():
    async with outbound_http_pool():
        async with pooled_http_client(timeout=3) as first:
            async with outbound_http_pool():
                async with pooled_http_client(timeout=7) as second:
                    assert first is not second
                    assert first.timeout.read == 3
                    assert second.timeout.read == 7
            assert not first.is_closed
            assert not second.is_closed
    assert first.is_closed and second.is_closed


@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
async def test_close_failure_preserves_original_outcome(monkeypatch, caplog, outcome):
    original_error = (
        asyncio.CancelledError() if outcome == "cancelled" else ValueError("task failed")
    )
    close_error = RuntimeError("secret-upstream-token")
    closes = [AsyncMock(side_effect=close_error), AsyncMock()]
    clients = iter(SimpleNamespace(aclose=close) for close in closes)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: next(clients))
    expected = close_error if outcome == "success" else original_error
    with pytest.raises(type(expected)) as caught:
        async with outbound_http_pool():
            async with pooled_http_client(timeout=1):
                pass
            async with pooled_http_client(timeout=2):
                pass
            if outcome != "success":
                raise original_error
    assert caught.value is expected
    for close in closes:
        close.assert_awaited_once()
    assert asyncio.get_running_loop() not in http_pool._pools
    assert "secret-upstream-token" not in caplog.text
    if outcome != "success":
        assert "outbound_http_pool_close_failed" in caplog.text


@pytest.mark.parametrize("managed", [False, True])
async def test_clients_close_on_failure_and_cancellation(managed):
    async def work():
        async with pooled_http_client(timeout=1) as client:
            clients.append(client)
            raise asyncio.CancelledError()

    clients = []
    with pytest.raises(asyncio.CancelledError):
        if managed:
            async with outbound_http_pool():
                await work()
        else:
            await work()
    assert clients[0].is_closed
    assert asyncio.get_running_loop() not in http_pool._pools


async def test_pool_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(http_pool, "_MAX_CLIENTS", 1)
    async with outbound_http_pool():
        async with pooled_http_client(timeout=1) as cached:
            pass
        async with pooled_http_client(timeout=2) as transient:
            assert not transient.is_closed
        assert transient.is_closed
        assert not cached.is_closed
        assert len(http_pool._pools[asyncio.get_running_loop()].clients) == 1


def test_separate_worker_event_loops_never_reuse_clients():
    async def work():
        async with outbound_http_pool():
            async with pooled_http_client(timeout=1) as client:
                return client

    first = asyncio.run(work())
    second = asyncio.run(work())
    assert first is not second
    assert first.is_closed and second.is_closed


def test_worker_runtime_owns_http_pool(monkeypatch):
    from app.worker import runtime

    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(runtime, "create_async_engine", lambda *args, **kwargs: engine)
    clients = []

    async def work(_maker):
        assert asyncio.get_running_loop() in http_pool._pools
        async with pooled_http_client(timeout=1) as client:
            clients.append(client)
        return "done"

    assert runtime.run_task(work) == "done"
    assert runtime.run_task(work) == "done"
    assert clients[0] is not clients[1]
    assert all(client.is_closed for client in clients)
    assert engine.dispose.await_count == 2


async def test_api_lifespan_owns_http_pool():
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        assert asyncio.get_running_loop() in http_pool._pools
        async with pooled_http_client(timeout=1) as client:
            assert not client.is_closed
    assert client.is_closed
    assert asyncio.get_running_loop() not in http_pool._pools


async def test_real_http_keepalive_reuses_tcp_connection(monkeypatch):
    # A workstation HTTP proxy can open a new upstream socket for every request.
    # Test the application's pool directly, not the workstation proxy's policy.
    monkeypatch.setenv("NO_PROXY", "127.0.0.1")
    connections = 0
    handlers = set()

    async def serve(reader, writer):
        nonlocal connections
        connections += 1
        task = asyncio.current_task()
        handlers.add(task)
        try:
            while True:
                await reader.readuntil(b"\r\n\r\n")
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
                await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            handlers.discard(task)

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        async with outbound_http_pool():
            for _ in range(3):
                async with pooled_http_client(timeout=5) as client:
                    response = await client.get(f"http://127.0.0.1:{port}/")
                    assert response.text == "ok"
        assert connections == 1
    finally:
        server.close()
        await server.wait_closed()
        await asyncio.gather(*handlers)

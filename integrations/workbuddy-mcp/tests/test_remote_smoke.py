"""远程 streamable-http smoke：证明工具可发现，且**每次请求的 Authorization Bearer**
被透传给 KAP（远程多用户身份），而非回退到进程级共享 token。

用真实 uvicorn + 真实 MCP streamable-http 客户端（不打公网）。
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import socket
import threading
import time

import httpx
import pytest


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _load_server(monkeypatch, captured: list):
    """以远程模式加载 server（进程级 token 设为可识别值，用于证明它**没被**使用）。"""
    monkeypatch.setenv("KAP_BASE_URL", "http://kap.test")
    monkeypatch.setenv("KAP_AGENT_TOKEN", "kgw_PROCESS_FALLBACK")
    monkeypatch.setenv("WORKBUDDY_MCP_TRANSPORT", "streamable-http")
    server = importlib.import_module("workbuddy_mcp.server")
    importlib.reload(server)

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request.headers.get("authorization"))
        return httpx.Response(200, json={"cards": []})

    # 拦截 KAP 侧 HTTP：记录工具实际发给 KAP 的 Authorization。
    server._client._http = httpx.Client(
        base_url="http://kap.test", transport=httpx.MockTransport(handler)
    )
    return server


@pytest.mark.skipif(
    importlib.util.find_spec("uvicorn") is None, reason="uvicorn 未安装，跳过远程 smoke"
)
def test_streamable_http_forwards_per_request_bearer(monkeypatch):
    import uvicorn
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    captured: list = []
    server = _load_server(monkeypatch, captured)
    port = _free_port()
    app = server.mcp.streamable_http_app()

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    userver = uvicorn.Server(config)
    thread = threading.Thread(target=userver.run, daemon=True)
    thread.start()
    # 等待端口就绪。
    for _ in range(50):
        if userver.started:
            break
        time.sleep(0.1)

    async def drive() -> tuple[list[str], str]:
        url = f"http://127.0.0.1:{port}/mcp"
        async with streamablehttp_client(
            url, headers={"Authorization": "Bearer kgw_USER_ALICE"}
        ) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = await s.list_tools()
                names = [t.name for t in tools.tools]
                res = await s.call_tool("kap_search_knowledge", {"query": "test"})
                return names, str(res.content)

    try:
        names, _ = asyncio.run(drive())
    finally:
        userver.should_exit = True
        thread.join(timeout=5)

    # 工具可被远程发现。
    assert "kap_search_knowledge" in names
    # 关键：KAP 收到的是**本次请求的用户 token**，不是进程级回退 token。
    assert captured, "工具未实际调用 KAP"
    assert captured[-1] == "Bearer kgw_USER_ALICE"
    assert captured[-1] != "Bearer kgw_PROCESS_FALLBACK"

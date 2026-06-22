"""server.py 构建期不应崩溃，且工具在后端错误时返回安全 error，不抛栈。"""

from __future__ import annotations

import importlib

import httpx


def test_tool_wrappers_sanitize_errors(monkeypatch):
    monkeypatch.setenv("KAP_BASE_URL", "http://kap.test")
    monkeypatch.setenv("KAP_AGENT_TOKEN", "kgw_x")
    server = importlib.import_module("workbuddy_mcp.server")
    importlib.reload(server)

    def handler(request):
        return httpx.Response(403, json={"detail": {"denied_reason": "caller_unresolved"}})

    # 注入 mock transport 到模块级 client。
    server._client._http = httpx.Client(
        base_url="http://kap.test", transport=httpx.MockTransport(handler)
    )

    out = server._search_tool("q", scope="project")
    assert "error" in out
    assert "caller_unresolved" not in out["error"]

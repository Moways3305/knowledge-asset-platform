"""server.py 构建期不应崩溃，且工具在后端错误时返回安全 error，不抛栈。"""

from __future__ import annotations

import asyncio
import importlib

import httpx

_EXPECTED_TOOLS = {
    "kap_search_knowledge",
    "kap_answer_from_knowledge",
    "kap_list_accessible_projects",
    "kap_list_my_todos",
    "kap_list_recent_knowledge",
    "kap_list_my_personal_knowledge",
    "kap_list_accessible_knowledge",
    "kap_get_knowledge_summary",
    "kap_get_knowledge_detail",
    "kap_get_knowledge_content",
    "kap_list_tags",
    "kap_list_project_knowledge",
    "kap_get_project_brief",
    "kap_list_pending_reviews",
    "kap_list_original_access_requests",
}


def test_all_readonly_tools_registered(monkeypatch):
    monkeypatch.setenv("KAP_BASE_URL", "http://kap.test")
    monkeypatch.setenv("KAP_AGENT_TOKEN", "kgw_x")
    server = importlib.import_module("workbuddy_mcp.server")
    importlib.reload(server)
    tools = asyncio.run(server.mcp.list_tools())
    names = {t.name for t in tools}
    assert _EXPECTED_TOOLS.issubset(names), _EXPECTED_TOOLS - names
    assert len(names) == 15


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

    def html_handler(request):
        return httpx.Response(301, text="<html>redirect</html>")

    server._client._http = httpx.Client(
        base_url="http://kap.test", transport=httpx.MockTransport(html_handler)
    )
    redirected = server._knowledge_content_tool("a1")
    assert redirected == {"error": "知识服务暂不可用，请稍后重试"}

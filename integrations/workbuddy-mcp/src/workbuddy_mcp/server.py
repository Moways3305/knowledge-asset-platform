"""WorkBuddy MCP server（stdio）。

暴露三个只读知识工具，全部经 KAP agent-gateway（权限 / 脱敏 / 审计在后端）。
身份由 KAP_AGENT_TOKEN 在后端绑定解析——本进程不接收、不配置任何 caller id。
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .config import load_config
from .kap_client import (
    KapClient,
    KapError,
    answer_from_knowledge,
    list_accessible_projects,
    search_knowledge,
)

_cfg = load_config()
_client = KapClient(_cfg)
mcp = FastMCP("workbuddy-kap")


def _search_tool(
    query: str,
    scope: str | None = None,
    top_k: int | None = None,
    tags: list[str] | None = None,
    phase: str | None = None,
):
    try:
        return search_knowledge(_client, query, scope=scope, top_k=top_k, tags=tags, phase=phase)
    except KapError as exc:
        return {"error": str(exc)}


def _answer_tool(query: str, scope: str | None = None):
    try:
        return answer_from_knowledge(_client, query, scope=scope)
    except KapError as exc:
        return {"error": str(exc)}


def _projects_tool():
    try:
        return list_accessible_projects(_client)
    except KapError as exc:
        return {"error": str(exc)}


@mcp.tool()
def kap_search_knowledge(
    query: str,
    scope: str | None = None,
    top_k: int | None = None,
    tags: list[str] | None = None,
    phase: str | None = None,
):
    """检索 KAP 知识，返回安全摘要卡片（按调用人权限裁剪 + 脱敏）。"""
    return _search_tool(query, scope=scope, top_k=top_k, tags=tags, phase=phase)


@mcp.tool()
def kap_answer_from_knowledge(query: str, scope: str | None = None):
    """基于 KAP 知识生成带引用的回答（权限受控、引用为脱敏片段）。"""
    return _answer_tool(query, scope=scope)


@mcp.tool()
def kap_list_accessible_projects():
    """列出当前绑定用户可访问的项目（最小安全字段）。"""
    return _projects_tool()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

"""WorkBuddy MCP server。

暴露三个只读知识工具，全部经 KAP agent-gateway（权限 / 脱敏 / 审计在后端）。
身份由 token 在 KAP 后端绑定解析——本进程不接收、不配置任何 caller id。

传输 / 身份（见 config.py）：
- stdio（默认）：进程级 KAP_AGENT_TOKEN 即身份（每用户一份配置）。
- streamable-http / sse（远程多用户）：身份来自**每次请求的 Authorization Bearer**
  （由 ctx 读取并透传给 KAP），进程级 token 只作个人本地测试的回退。

安全红线：远程模式下若一律使用进程级 token，则所有人会被映射到同一身份——这只能用于个人
本地测试，**绝不可**作为公司共享服务。公司共享远程 MCP 必须让每次调用使用该用户自己的
Bearer（本实现已支持 per-request 透传）。
"""

from __future__ import annotations

from mcp.server.fastmcp import Context, FastMCP

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


def _read_bearer(ctx: Context | None) -> str | None:
    """从本次请求的 Authorization 头取 Bearer（仅 HTTP 传输有 request；stdio 返回 None）。

    取到则用调用人本人 token（远程多用户）；取不到则回退进程级 token（stdio / 个人远程测试）。
    """
    if ctx is None:
        return None
    try:
        req = getattr(ctx.request_context, "request", None)
        auth = req.headers.get("authorization") if req is not None else None
    except Exception:  # noqa: BLE001  # 任何读取异常都安全回退，不外泄
        return None
    if not auth:
        return None
    parts = auth.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        return None
    return parts[1].strip()


# 纯函数工具层（可单测；不依赖 MCP 运行时）。bearer=None → KapClient 用进程级 token。
def _search_tool(query, scope=None, top_k=None, tags=None, phase=None, *, bearer=None):
    try:
        return search_knowledge(
            _client, query, scope=scope, top_k=top_k, tags=tags, phase=phase, bearer=bearer
        )
    except KapError as exc:
        return {"error": str(exc)}


def _answer_tool(query, scope=None, *, bearer=None):
    try:
        return answer_from_knowledge(_client, query, scope=scope, bearer=bearer)
    except KapError as exc:
        return {"error": str(exc)}


def _projects_tool(*, bearer=None):
    try:
        return list_accessible_projects(_client, bearer=bearer)
    except KapError as exc:
        return {"error": str(exc)}


@mcp.tool()
def kap_search_knowledge(
    query: str,
    scope: str | None = None,
    top_k: int | None = None,
    tags: list[str] | None = None,
    phase: str | None = None,
    ctx: Context | None = None,
) -> object:
    """检索 KAP 知识，返回安全摘要卡片（按调用人权限裁剪 + 脱敏）。"""
    return _search_tool(query, scope, top_k, tags, phase, bearer=_read_bearer(ctx))


@mcp.tool()
def kap_answer_from_knowledge(
    query: str, scope: str | None = None, ctx: Context | None = None
) -> object:
    """基于 KAP 知识生成带引用的回答（权限受控、引用为脱敏片段）。"""
    return _answer_tool(query, scope, bearer=_read_bearer(ctx))


@mcp.tool()
def kap_list_accessible_projects(ctx: Context | None = None) -> object:
    """列出当前调用人可访问的项目（最小安全字段）。"""
    return _projects_tool(bearer=_read_bearer(ctx))


def main() -> None:
    if _cfg.transport in ("streamable-http", "sse"):
        mcp.settings.host = _cfg.host
        mcp.settings.port = _cfg.port
        mcp.run(transport=_cfg.transport)
    else:
        mcp.run()


if __name__ == "__main__":
    main()

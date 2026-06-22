"""WorkBuddy MCP 配置。

传输方式（WORKBUDDY_MCP_TRANSPORT，默认 stdio）：
- stdio：本地子进程，进程级 KAP_AGENT_TOKEN 即身份（每用户一份配置）→ token 必填。
- streamable-http / sse：远程多用户，身份由**每次请求的 Authorization Bearer** 决定
  （见 server.py 的 per-request 透传）→ 进程级 KAP_AGENT_TOKEN 可选（留空表示纯多用户远程，
  仅当作个人本地测试时才填）。

红线：任何模式都**不接收 caller / KAP user id**——身份只由 token 在 KAP 后端绑定解析。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_VALID_TRANSPORTS = ("stdio", "sse", "streamable-http")


@dataclass(frozen=True)
class Config:
    base_url: str
    agent_token: str  # 远程模式可为空（身份走 per-request bearer）
    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000


def load_config(env: dict | None = None) -> Config:
    env = env if env is not None else dict(os.environ)
    base_url = (env.get("KAP_BASE_URL") or "").strip()
    token = (env.get("KAP_AGENT_TOKEN") or "").strip()
    transport = (env.get("WORKBUDDY_MCP_TRANSPORT") or "stdio").strip()
    host = (env.get("WORKBUDDY_MCP_HOST") or "127.0.0.1").strip()
    port_raw = (env.get("WORKBUDDY_MCP_PORT") or "8000").strip()

    if transport not in _VALID_TRANSPORTS:
        raise RuntimeError(
            f"WORKBUDDY_MCP_TRANSPORT 非法: {transport!r}（可选 {', '.join(_VALID_TRANSPORTS)}）"
        )
    try:
        port = int(port_raw)
    except ValueError:
        raise RuntimeError(f"WORKBUDDY_MCP_PORT 非法: {port_raw!r}") from None

    missing = []
    if not base_url:
        missing.append("KAP_BASE_URL")
    # stdio：进程级 token 即身份，必填。远程多用户：token 可选（per-request bearer 提供身份）。
    if transport == "stdio" and not token:
        missing.append("KAP_AGENT_TOKEN")
    if missing:
        raise RuntimeError("WorkBuddy MCP 缺少必需配置: " + ", ".join(missing))

    return Config(
        base_url=base_url.rstrip("/"),
        agent_token=token,
        transport=transport,
        host=host,
        port=port,
    )

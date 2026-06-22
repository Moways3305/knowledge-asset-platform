"""WorkBuddy MCP 配置。仅 KAP_BASE_URL + KAP_AGENT_TOKEN；缺失即 fail-closed。

红线：不存在 caller / KAP user id 配置项——身份只由 token 绑定在 KAP 后端解析。
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    base_url: str
    agent_token: str


def load_config(env: dict | None = None) -> Config:
    env = env if env is not None else dict(os.environ)
    base_url = (env.get("KAP_BASE_URL") or "").strip()
    token = (env.get("KAP_AGENT_TOKEN") or "").strip()
    missing = [n for n, v in (("KAP_BASE_URL", base_url), ("KAP_AGENT_TOKEN", token)) if not v]
    if missing:
        raise RuntimeError("WorkBuddy MCP 缺少必需配置: " + ", ".join(missing))
    return Config(base_url=base_url.rstrip("/"), agent_token=token)

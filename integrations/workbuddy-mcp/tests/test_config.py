"""配置解析：传输方式 + 远程模式下 token 可选。"""

from __future__ import annotations

import pytest

from workbuddy_mcp.config import load_config


def test_stdio_requires_token():
    with pytest.raises(RuntimeError) as e:
        load_config({"KAP_BASE_URL": "http://kap.test"})  # 默认 stdio，缺 token
    assert "KAP_AGENT_TOKEN" in str(e.value)


def test_remote_token_optional():
    cfg = load_config(
        {
            "KAP_BASE_URL": "http://kap.test",
            "WORKBUDDY_MCP_TRANSPORT": "streamable-http",
            "WORKBUDDY_MCP_HOST": "0.0.0.0",
            "WORKBUDDY_MCP_PORT": "9000",
        }
    )
    assert cfg.transport == "streamable-http"
    assert cfg.agent_token == ""  # 远程多用户：身份走 per-request bearer
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 9000


def test_base_url_always_required():
    with pytest.raises(RuntimeError) as e:
        load_config({"WORKBUDDY_MCP_TRANSPORT": "streamable-http"})
    assert "KAP_BASE_URL" in str(e.value)


def test_invalid_transport_rejected():
    with pytest.raises(RuntimeError):
        load_config(
            {"KAP_BASE_URL": "http://kap.test", "WORKBUDDY_MCP_TRANSPORT": "ftp"}
        )

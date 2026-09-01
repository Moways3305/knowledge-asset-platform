"""WorkBuddy remote Streamable HTTP protocol, auth and tool-contract tests."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import select

from app.db.utils import utc_now
from app.main import app
from app.models.agent_registry import AgentWhitelistRule
from app.seed.dev_seed import USER_CONSULTANT
from app.services.workbuddy_remote_mcp import _TOOL_NAMES

REGENERATE = "/api/v1/auth/workbuddy-token/regenerate"


def test_remote_mcp_edge_is_exact_bounded_and_loopback_only():
    root = Path(__file__).resolve().parents[2]
    inner = (root / "deploy" / "nginx.conf.template").read_text(encoding="utf-8")
    main = (root / "deploy" / "nginx-main.conf").read_text(encoding="utf-8")
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")

    assert "location = /mcp" in inner
    assert "client_max_body_size 64k;" in inner
    assert "proxy_buffering off;" in inner
    assert "zone=workbuddy_mcp" in inner and "zone=workbuddy_mcp" in main
    assert "proxy_set_header X-Forwarded-Proto $kap_forwarded_proto;" in inner
    assert '"127.0.0.1:18080:8080"' in compose


def _dev(user_id):
    return {"X-Dev-User-Id": str(user_id)}


async def _remote_token(client) -> tuple[str, dict]:
    response = await client.post(
        REGENERATE,
        headers=_dev(USER_CONSULTANT),
        json={"mode": "remote"},
    )
    assert response.status_code == 200, response.text
    return response.json()["token"], response.json()


async def _mcp_session(token: str):
    transport = httpx.ASGITransport(app=app)
    http = httpx.AsyncClient(
        transport=transport,
        base_url="https://test",
        headers={"Authorization": f"Bearer {token}"},
    )
    streams = streamable_http_client("https://test/mcp", http_client=http)
    read_stream, write_stream, _ = await streams.__aenter__()
    session_context = ClientSession(read_stream, write_stream)
    session = await session_context.__aenter__()
    return http, streams, session_context, session


async def _close_mcp(resources) -> None:
    http, streams, session_context, _session = resources
    await session_context.__aexit__(None, None, None)
    await streams.__aexit__(None, None, None)
    await http.aclose()


async def test_remote_config_is_https_shape_with_one_time_bearer(client):
    token, body = await _remote_token(client)
    kap = body["mcp_config"]["mcpServers"]["kap"]

    assert body["mode"] == "remote"
    assert body["expires_at"] is not None
    assert kap == {
        "type": "http",
        "url": "http://localhost:8000/mcp",
        "headers": {"Authorization": f"Bearer {token}"},
    }
    assert "command" not in kap and "env" not in kap
    assert "token_hash" not in str(body)


async def test_initialize_lists_all_tools_and_real_read_matches_gateway(client):
    token, _ = await _remote_token(client)
    direct = await client.get(
        "/api/v1/agent-gateway/projects",
        headers={"Authorization": f"Bearer {token}"},
    )
    knowledge = await client.get(
        "/api/v1/agent-gateway/knowledge?limit=1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert direct.status_code == knowledge.status_code == 200
    project_id = direct.json()["items"][0]["project_id"]
    asset_id = knowledge.json()["items"][0]["asset_id"]
    tool_calls = {
        "kap_search_knowledge": {"query": "test"},
        "kap_list_knowledge_directories": {},
        "kap_answer_from_knowledge": {"query": "test"},
        "kap_list_accessible_projects": {},
        "kap_list_my_todos": {},
        "kap_list_recent_knowledge": {},
        "kap_list_my_personal_knowledge": {},
        "kap_list_accessible_knowledge": {},
        "kap_get_knowledge_summary": {"asset_id": asset_id},
        "kap_get_knowledge_detail": {"asset_id": asset_id},
        "kap_get_knowledge_content": {"asset_id": asset_id},
        "kap_list_tags": {},
        "kap_list_project_knowledge": {"project_id": project_id},
        "kap_get_project_brief": {"project_id": project_id},
        "kap_list_pending_reviews": {},
        "kap_list_original_access_requests": {},
    }
    async with app.router.lifespan_context(app):
        resources = await _mcp_session(token)
        session = resources[-1]
        try:
            initialized = await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool("kap_list_accessible_projects", {})
            contract_results = {
                name: await session.call_tool(name, arguments)
                for name, arguments in tool_calls.items()
            }
        finally:
            await _close_mcp(resources)

        bad_origin = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={
                "Accept": "application/json, text/event-stream",
                "Authorization": f"Bearer {token}",
                "Origin": "https://attacker.invalid",
            },
        )
        oversized = await client.post(
            "/mcp",
            content=b"x" * 70000,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )

    assert initialized.serverInfo.name == "KAP WorkBuddy"
    assert {tool.name for tool in tools.tools} == set(_TOOL_NAMES)
    assert result.isError is False
    failures = {
        name: [getattr(content, "text", "") for content in item.content]
        for name, item in contract_results.items()
        if item.isError
    }
    # The seeded first asset is deliberately summary-only for this caller, so the
    # original-content tool must exercise its permission-denied contract.
    assert set(failures) == {"kap_get_knowledge_content"}
    assert [json.loads(item.text) for item in result.content] == direct.json()["items"]
    assert bad_origin.status_code in {400, 403, 421}
    assert oversized.status_code == 413
    assert token not in oversized.text


async def test_missing_expired_and_revoked_credentials_are_rejected(client, db_session):
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "contract-test", "version": "1"},
        },
    }
    unauthenticated = await client.post(
        "/mcp",
        json=initialize,
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert unauthenticated.status_code == 401

    token, _ = await _remote_token(client)
    rule = (
        await db_session.execute(
            select(AgentWhitelistRule).where(
                AgentWhitelistRule.bound_user_id == USER_CONSULTANT,
                AgentWhitelistRule.is_self_service.is_(True),
            )
        )
    ).scalar_one()
    rule.token_expires_at = utc_now() - timedelta(seconds=1)
    await db_session.commit()
    expired = await client.post(
        "/mcp",
        json=initialize,
        headers={
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {token}",
        },
    )
    assert expired.status_code == 401

    renewed, _ = await _remote_token(client)
    revoked = await client.delete("/api/v1/auth/workbuddy-token", headers=_dev(USER_CONSULTANT))
    assert revoked.status_code == 200
    after_revoke = await client.post(
        "/mcp",
        json=initialize,
        headers={
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {renewed}",
        },
    )
    assert after_revoke.status_code == 401

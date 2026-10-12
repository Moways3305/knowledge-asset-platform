"""Real SDK endpoints, PKCE, consent, live permissions and token rotation."""

import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select
from test_workbuddy_remote_mcp import _close_mcp, _mcp_session

from app.core.config import get_settings
from app.main import app, create_app
from app.models.agent_registry import AgentWhitelistRule
from app.models.identity import User
from app.models.mcp_oauth import McpOAuthRecord
from app.seed.dev_seed import USER_ADMIN_ONLY, USER_BOSS, USER_CONSULTANT, USER_DIRECTOR


@pytest.fixture
async def oauth_client(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "mcp_oauth_enabled", True)
    monkeypatch.setattr(settings, "mcp_oauth_client_encryption_key", Fernet.generate_key().decode())
    oauth_app = create_app()
    oauth_app.dependency_overrides.update(app.dependency_overrides)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=oauth_app), base_url="https://test"
    ) as http:
        http.oauth_app = oauth_app
        yield http


def headers(user=USER_CONSULTANT):
    return {"X-Dev-User-Id": str(user)}


async def register(client, **kwargs):
    result = await client.post(
        "/register",
        json={
            "client_name": "Test assistant",
            "redirect_uris": ["https://assistant.example/callback"],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            **kwargs,
        },
    )
    assert result.status_code == 201, result.text
    return result.json()


async def authorize(client, registration, scope="qa"):
    verifier = "a" * 64
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    response = await client.get(
        "/authorize",
        params={
            "client_id": registration["client_id"],
            "redirect_uri": registration["redirect_uris"][0],
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": scope,
            "state": "original-state",
            "resource": client.oauth_app.state.mcp_oauth_provider.resource,
        },
    )
    assert response.status_code == 302, response.text
    request_id = parse_qs(urlsplit(response.headers["location"]).query)["request"][0]
    return request_id, verifier


async def exchange(
    client, registration, request_id, verifier, user=USER_CONSULTANT, operations=False
):
    result = await client.post(
        f"/api/v1/auth/mcp-oauth/requests/{request_id}",
        headers=headers(user),
        json={"approved": True, "operations": operations},
    )
    assert result.status_code == 200, result.text
    query = parse_qs(urlsplit(result.json()["redirect_url"]).query)
    assert query["state"] == ["original-state"]
    data = {
        "grant_type": "authorization_code",
        "client_id": registration["client_id"],
        "code": query["code"][0],
        "code_verifier": verifier,
        "redirect_uri": registration["redirect_uris"][0],
        "resource": client.oauth_app.state.mcp_oauth_provider.resource,
    }
    result = await client.post("/token", data=data)
    assert result.status_code == 200, result.text
    return result.json(), data


@pytest.mark.parametrize("user", [USER_CONSULTANT, USER_DIRECTOR, USER_BOSS])
async def test_oauth_end_to_end_rotation_and_owned_revocation(oauth_client, db_session, user):
    client = oauth_client
    metadata = await client.get("/.well-known/oauth-authorization-server")
    assert metadata.status_code == 200
    assert metadata.json()["token_endpoint"].endswith("/token")
    resource = await client.get("/.well-known/oauth-protected-resource/mcp")
    assert resource.status_code == 200 and "authorization_servers" in resource.json()
    registration = await register(client)
    request_id, verifier = await authorize(client, registration)
    view = await client.get(f"/api/v1/auth/mcp-oauth/requests/{request_id}", headers=headers(user))
    assert view.status_code == 200 and not view.json()["operations_requested"]
    tokens, data = await exchange(client, registration, request_id, verifier, user)
    assert (await client.post("/token", data=data)).status_code == 400
    provider = client.oauth_app.state.mcp_oauth_provider
    assert await provider.load_access_token(tokens["access_token"])
    rule = await db_session.scalar(
        select(AgentWhitelistRule).where(
            AgentWhitelistRule.bound_user_id == user,
            AgentWhitelistRule.is_mcp_oauth_grant.is_(True),
        )
    )
    assert rule.capability == "qa"
    assert rule.token_hash != tokens["access_token"]
    refreshed = await client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "client_id": registration["client_id"],
            "refresh_token": tokens["refresh_token"],
        },
    )
    assert refreshed.status_code == 200, refreshed.text
    assert not await provider.load_access_token(tokens["access_token"])
    new_token = refreshed.json()["access_token"]
    assert await provider.load_access_token(new_token)
    grants = (await client.get("/api/v1/auth/mcp-oauth/grants", headers=headers(user))).json()
    grant_id = grants["items"][0]["id"]
    assert (
        await client.delete(
            f"/api/v1/auth/mcp-oauth/grants/{grant_id}", headers=headers(USER_ADMIN_ONLY)
        )
    ).status_code == 404
    assert (
        await client.delete(f"/api/v1/auth/mcp-oauth/grants/{grant_id}", headers=headers(user))
    ).status_code == 200
    assert not await provider.load_access_token(new_token)
    rows = (await db_session.scalars(select(McpOAuthRecord))).all()
    assert tokens["refresh_token"] not in str([row.payload for row in rows])


async def test_explicit_operations_consent_and_invalid_pkce(oauth_client):
    client = oauth_client
    registration = await register(client, scope="qa qa_operations")
    request_id, verifier = await authorize(client, registration, "qa qa_operations")
    route = f"/api/v1/auth/mcp-oauth/requests/{request_id}"
    assert (
        await client.post(
            route, headers=headers(USER_ADMIN_ONLY), json={"approved": True, "operations": True}
        )
    ).status_code == 403
    assert (await client.post(route, headers=headers(), json={"approved": True})).status_code == 422
    result = await client.post(
        route, headers=headers(), json={"approved": True, "operations": True}
    )
    code = parse_qs(urlsplit(result.json()["redirect_url"]).query)["code"][0]
    data = {
        "grant_type": "authorization_code",
        "client_id": registration["client_id"],
        "code": code,
        "code_verifier": "b" * 64,
        "redirect_uri": registration["redirect_uris"][0],
    }
    assert (await client.post("/token", data=data)).status_code == 400
    data["code_verifier"] = verifier
    result = await client.post("/token", data=data)
    assert result.status_code == 200, result.text
    token = await client.oauth_app.state.mcp_oauth_provider.load_access_token(
        result.json()["access_token"]
    )
    assert "qa_operations" in token.scopes


async def test_unsafe_redirect_and_wrong_resource_rejected(oauth_client):
    client = oauth_client
    for uri in [
        "http://evil.example/cb",
        "javascript:alert(1)",
        "https://user:password@example.com/cb",
    ]:
        result = await client.post(
            "/register",
            json={
                "redirect_uris": [uri],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
        assert result.status_code == 400, result.text
    registration = await register(client)
    response = await client.get(
        "/authorize",
        params={
            "client_id": registration["client_id"],
            "redirect_uri": registration["redirect_uris"][0],
            "response_type": "code",
            "code_challenge": "x" * 43,
            "code_challenge_method": "S256",
            "scope": "qa",
            "resource": "https://evil.example/mcp",
        },
    )
    assert response.status_code in {302, 400}
    assert "/mcp-authorize" not in response.headers.get("location", "")


async def test_confidential_client_secret_encrypted_and_refresh_replay_revokes(
    oauth_client, db_session
):
    client = oauth_client
    registration = await register(client, token_endpoint_auth_method="client_secret_post")
    row = await db_session.scalar(select(McpOAuthRecord).where(McpOAuthRecord.kind == "client"))
    assert registration["client_secret"] not in str(row.payload)
    request_id, verifier = await authorize(client, registration)
    # Supply the registered secret for token exchanges.
    result = await client.post(
        f"/api/v1/auth/mcp-oauth/requests/{request_id}", headers=headers(), json={"approved": True}
    )
    code = parse_qs(urlsplit(result.json()["redirect_url"]).query)["code"][0]
    result = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": registration["client_id"],
            "client_secret": registration["client_secret"],
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": registration["redirect_uris"][0],
        },
    )
    assert result.status_code == 200, result.text
    tokens = result.json()
    refresh_data = {
        "grant_type": "refresh_token",
        "client_id": registration["client_id"],
        "client_secret": registration["client_secret"],
        "refresh_token": tokens["refresh_token"],
    }
    rotated = await client.post("/token", data=refresh_data)
    assert rotated.status_code == 200, rotated.text
    assert (await client.post("/token", data=refresh_data)).status_code == 400
    assert not await client.oauth_app.state.mcp_oauth_provider.load_access_token(
        rotated.json()["access_token"]
    )


async def test_real_mcp_call_and_legacy_bearer_remain_compatible(oauth_client):
    client = oauth_client
    registration = await register(client)
    request_id, verifier = await authorize(client, registration)
    tokens, _ = await exchange(client, registration, request_id, verifier)
    legacy = await client.post(
        "/api/v1/auth/workbuddy-token/regenerate", headers=headers(), json={"mode": "remote"}
    )
    assert legacy.status_code == 200, legacy.text
    target_app = client.oauth_app
    async with target_app.router.lifespan_context(target_app):
        for token in (tokens["access_token"], legacy.json()["token"]):
            resources = await _mcp_session(token, target_app)
            try:
                session = resources[-1]
                await session.initialize()
                result = await session.call_tool(
                    "kap_list_accessible_knowledge", {"scope": "company", "limit": 1}
                )
                assert not result.isError, result
            finally:
                await _close_mcp(resources)


async def test_registration_request_size_is_bounded(oauth_client):
    result = await oauth_client.post("/register", content=b"x" * 65537)
    assert result.status_code == 413


async def test_oauth_live_user_disable_and_readonly_operations(oauth_client, db_session):
    client = oauth_client
    registration = await register(client)
    request_id, verifier = await authorize(client, registration)
    tokens, _ = await exchange(client, registration, request_id, verifier)
    assert (
        await client.get(
            "/api/v1/agent-gateway/operations/upload-destinations",
            headers={"Authorization": "Bearer " + tokens["access_token"]},
        )
    ).status_code == 403
    user = await db_session.get(User, USER_CONSULTANT)
    user.status = "inactive"
    await db_session.commit()
    assert not await client.oauth_app.state.mcp_oauth_provider.load_access_token(
        tokens["access_token"]
    )
    result = await client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "client_id": registration["client_id"],
            "refresh_token": tokens["refresh_token"],
        },
    )
    assert result.status_code == 400


async def test_sdk_revocation_and_operations_authorization(oauth_client):
    client = oauth_client
    registration = await register(client, scope="qa qa_operations")
    request_id, verifier = await authorize(client, registration, "qa qa_operations")
    tokens, _ = await exchange(client, registration, request_id, verifier, operations=True)
    target_app = client.oauth_app
    async with target_app.router.lifespan_context(target_app):
        resources = await _mcp_session(tokens["access_token"], target_app)
        try:
            session = resources[-1]
            await session.initialize()
            result = await session.call_tool("kap_list_upload_destinations", {})
            assert not result.isError, result
        finally:
            await _close_mcp(resources)
    result = await client.post(
        "/revoke",
        data={
            "client_id": registration["client_id"],
            "token": tokens["refresh_token"],
            "token_type_hint": "refresh_token",
        },
    )
    assert result.status_code == 200, result.text
    assert not await target_app.state.mcp_oauth_provider.load_access_token(tokens["access_token"])

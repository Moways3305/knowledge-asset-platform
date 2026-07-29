"""自助 WorkBuddy token、平台配置、连接状态与安装产物授权测试。"""

from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import select

from app.models.audit import AuditEvent
from app.models.identity import User, UserCompanyRole
from app.seed.dev_seed import USER_ADMIN_ONLY, USER_CONSULTANT

TOKEN_URL = "/api/v1/auth/workbuddy-token"
REGEN_URL = "/api/v1/auth/workbuddy-token/regenerate"
CONNECTORS_URL = "/api/v1/auth/workbuddy-connectors"
SEARCH = "/api/v1/agent-gateway/tools/knowledge-search"
PROJECTS = "/api/v1/agent-gateway/projects"
LOGIN = "/api/v1/auth/login"
CSRF = "/api/v1/auth/csrf"
BOSS_EMAIL = "boss.c@dev.local"


def _dev(user_id):
    return {"X-Dev-User-Id": str(user_id)}


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


async def _regen(client, platform="windows"):
    return await client.post(REGEN_URL, headers=_dev(USER_CONSULTANT), json={"platform": platform})


async def test_get_status_none_for_business_user(client):
    response = await client.get(TOKEN_URL, headers=_dev(USER_CONSULTANT))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is False
    assert body["last_connected_at"] is None
    assert "bound_user_id" not in body
    assert "token" not in body and "token_hash" not in body


async def test_regenerate_returns_windows_connector_config(client):
    response = await _regen(client)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token"].startswith("kgw_")
    assert body["platform"] == "windows"
    kap = body["mcp_config"]["mcpServers"]["kap"]
    assert kap["env"]["KAP_AGENT_TOKEN"] == body["token"]
    assert kap["env"]["KAP_BASE_URL"]
    assert kap["command"].endswith("kap-workbuddy-connector.exe")
    assert "python" not in json.dumps(kap).lower()
    assert "token_hash" not in response.text


async def test_regenerate_returns_macos_connector_config(client):
    response = await _regen(client, "macos")
    assert response.status_code == 200, response.text
    kap = response.json()["mcp_config"]["mcpServers"]["kap"]
    assert kap["command"] == (
        "/Applications/KAP WorkBuddy Connector.app/Contents/MacOS/kap-workbuddy-connector"
    )
    assert "python" not in json.dumps(kap).lower()


async def test_get_after_regenerate_hides_token(client):
    await _regen(client)
    response = await client.get(TOKEN_URL, headers=_dev(USER_CONSULTANT))
    body = response.json()
    assert body["enabled"] is True
    assert body["bound_user_name"]
    assert body["last_rotated_at"]
    assert body["last_connected_at"] is None
    assert "token" not in body and "token_hash" not in body
    assert "kgw_" not in response.text


async def test_regenerate_rotates_and_invalidates_old(client):
    token_one = (await _regen(client)).json()["token"]
    assert (
        await client.post(SEARCH, headers=_bearer(token_one), json={"query": "test"})
    ).status_code == 200
    token_two = (await _regen(client, "macos")).json()["token"]
    assert token_two != token_one
    assert (
        await client.post(SEARCH, headers=_bearer(token_one), json={"query": "test"})
    ).status_code == 403
    assert (
        await client.post(SEARCH, headers=_bearer(token_two), json={"query": "test"})
    ).status_code == 200


async def test_revoke_disables_token(client):
    token = (await _regen(client)).json()["token"]
    assert (
        await client.post(SEARCH, headers=_bearer(token), json={"query": "test"})
    ).status_code == 200
    deleted = await client.delete(TOKEN_URL, headers=_dev(USER_CONSULTANT))
    assert deleted.status_code == 200, deleted.text
    assert (
        await client.post(SEARCH, headers=_bearer(token), json={"query": "test"})
    ).status_code == 403
    assert (await client.get(TOKEN_URL, headers=_dev(USER_CONSULTANT))).json()["enabled"] is False


async def test_body_bound_user_id_ignored_and_not_returned(client):
    response = await client.post(
        REGEN_URL,
        headers=_dev(USER_CONSULTANT),
        json={"platform": "windows", "bound_user_id": str(uuid.uuid4())},
    )
    assert response.status_code == 200, response.text
    status = (await client.get(TOKEN_URL, headers=_dev(USER_CONSULTANT))).json()
    assert "bound_user_id" not in status


async def test_pure_admin_forbidden(client):
    assert (await client.get(TOKEN_URL, headers=_dev(USER_ADMIN_ONLY))).status_code == 403
    response = await client.post(
        REGEN_URL, headers=_dev(USER_ADMIN_ONLY), json={"platform": "windows"}
    )
    assert response.status_code == 403


async def test_inactive_business_user_forbidden(client, db_session):
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        name="停用员工",
        email=f"x{user_id.hex[:6]}@dev.local",
        status="inactive",
    )
    user.company_roles.append(UserCompanyRole(company_role="consultant", status="active"))
    db_session.add(user)
    await db_session.commit()
    assert (await client.get(TOKEN_URL, headers=_dev(user_id))).status_code == 403


async def test_audit_actions_no_leak(client, db_session):
    token = (await _regen(client)).json()["token"]
    await client.delete(TOKEN_URL, headers=_dev(USER_CONSULTANT))
    logs = (await db_session.execute(select(AuditEvent))).scalars().all()
    actions = {log.action for log in logs}
    assert "agent.workbuddy_token_rotated" in actions
    assert "agent.workbuddy_token_revoked" in actions
    blob = json.dumps([log.extra for log in logs], ensure_ascii=False)
    assert token not in blob
    for key in ("token_hash", "kgw_", "Authorization", "cookie"):
        assert key not in blob


async def test_regenerate_requires_csrf_under_cookie_session(client):
    await client.post(LOGIN, json={"email": BOSS_EMAIL})
    response = await client.post(REGEN_URL, json={"platform": "windows"})
    assert response.status_code == 403
    assert response.json()["detail"]["denied_reason"] == "csrf_token_missing"
    csrf = (await client.get(CSRF)).json()["csrf_token"]
    created = await client.post(
        REGEN_URL, headers={"X-CSRF-Token": csrf}, json={"platform": "windows"}
    )
    assert created.status_code == 200, created.text
    assert created.json()["token"].startswith("kgw_")


async def test_only_successful_gateway_call_updates_last_connected(client):
    token = (await _regen(client)).json()["token"]
    initial = (await client.get(TOKEN_URL, headers=_dev(USER_CONSULTANT))).json()
    assert initial["last_connected_at"] is None

    failed = await client.get(
        f"/api/v1/agent-gateway/projects/{uuid.uuid4()}/knowledge",
        headers=_bearer(token),
    )
    assert failed.status_code == 404
    after_failed = (await client.get(TOKEN_URL, headers=_dev(USER_CONSULTANT))).json()
    assert after_failed["last_connected_at"] is None

    succeeded = await client.get(PROJECTS, headers=_bearer(token))
    assert succeeded.status_code == 200, succeeded.text
    after_success = (await client.get(TOKEN_URL, headers=_dev(USER_CONSULTANT))).json()
    assert after_success["last_connected_at"] is not None
    assert "token" not in after_success and "token_hash" not in after_success


def _write_connector_manifest(tmp_path, monkeypatch, *, channel="internal", signed=False):
    from app.core.config import get_settings

    root = tmp_path / "connectors"
    root.mkdir()
    artifacts = []
    for platform, architecture, suffix in (
        ("windows", "x64", ".exe"),
        ("macos", "arm64", "-arm64.pkg"),
        ("macos", "x64", "-x64.pkg"),
    ):
        filename = f"kap-workbuddy-connector-1.0.0-{platform}-{architecture}{suffix}"
        payload = f"shared-{platform}-{architecture}".encode()
        (root / filename).write_bytes(payload)
        artifacts.append(
            {
                "platform": platform,
                "architecture": architecture,
                "filename": filename,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "signed": signed,
                "notarized": signed and platform == "macos",
            }
        )
    (root / "manifest.json").write_text(
        json.dumps({"version": "1.0.0", "channel": channel, "artifacts": artifacts}),
        encoding="utf-8",
    )
    monkeypatch.setattr(get_settings(), "workbuddy_connector_artifact_root", str(root))
    return artifacts


async def test_business_user_can_list_and_download_shared_connector(client, tmp_path, monkeypatch):
    artifacts = _write_connector_manifest(tmp_path, monkeypatch)
    token = (await _regen(client)).json()["token"]
    response = await client.get(CONNECTORS_URL, headers=_dev(USER_CONSULTANT))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version"] == "1.0.0"
    assert {(item["platform"], item["architecture"]) for item in body["artifacts"]} == {
        ("windows", "x64"),
        ("macos", "arm64"),
        ("macos", "x64"),
    }
    for leak in ("kgw_", "token_hash", "Authorization", str(USER_CONSULTANT)):
        assert leak not in response.text

    download = await client.get(
        f"{CONNECTORS_URL}/windows/x64/download",
        headers=_dev(USER_CONSULTANT),
    )
    assert download.status_code == 200
    assert download.content == b"shared-windows-x64"
    assert artifacts[0]["filename"] in download.headers["content-disposition"]
    # 查看清单或下载安装包不轮换个人 token；原配置继续有效。
    assert (await client.get(PROJECTS, headers=_bearer(token))).status_code == 200


async def test_connector_download_requires_business_user(client, tmp_path, monkeypatch):
    _write_connector_manifest(tmp_path, monkeypatch)
    assert (await client.get(CONNECTORS_URL, headers=_dev(USER_ADMIN_ONLY))).status_code == 403


async def test_connector_download_fails_safely_for_missing_or_tampered_file(
    client, tmp_path, monkeypatch
):
    artifacts = _write_connector_manifest(tmp_path, monkeypatch)
    root = tmp_path / "connectors"
    target = root / artifacts[0]["filename"]
    target.write_bytes(b"tampered")
    tampered = await client.get(CONNECTORS_URL, headers=_dev(USER_CONSULTANT))
    assert tampered.status_code == 503
    assert tampered.json()["detail"]["denied_reason"] == "workbuddy_connector_integrity_failed"
    assert "tampered" not in tampered.text

    target.unlink()
    missing = await client.get(CONNECTORS_URL, headers=_dev(USER_CONSULTANT))
    assert missing.status_code == 503
    assert missing.json()["detail"]["denied_reason"] == "workbuddy_connector_unavailable"
    assert artifacts[0]["filename"] not in missing.text


async def test_production_manifest_fails_closed_without_signatures(client, tmp_path, monkeypatch):
    from app.core.config import get_settings

    _write_connector_manifest(tmp_path, monkeypatch, channel="production", signed=False)
    await client.post(LOGIN, json={"email": BOSS_EMAIL})
    monkeypatch.setattr(get_settings(), "app_env", "prod")
    response = await client.get(CONNECTORS_URL)
    assert response.status_code == 503
    assert response.json()["detail"]["denied_reason"] == "workbuddy_connector_unsigned"

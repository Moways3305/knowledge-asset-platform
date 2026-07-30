"""自助 WorkBuddy token、平台配置、连接状态与安装产物授权测试。"""

from __future__ import annotations

import hashlib
import json
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import get_settings
from app.models.agent_registry import AgentWhitelistRule
from app.models.audit import AuditEvent
from app.models.identity import User, UserCompanyRole
from app.seed.dev_seed import USER_ADMIN_ONLY, USER_CONSULTANT
from app.services import workbuddy_token as workbuddy_token_service
from app.services.agent_registry import hash_token

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


async def test_public_origin_is_server_controlled_and_normalized(client):
    settings = get_settings()
    old_env, old_url = settings.app_env, settings.kap_public_base_url
    settings.app_env = "local"
    settings.kap_public_base_url = "https://knowledge.example.test/"
    try:
        response = await client.post(
            REGEN_URL,
            headers={
                **_dev(USER_CONSULTANT),
                "Host": "attacker.invalid",
                "Forwarded": "host=attacker.invalid;proto=http",
                "X-Forwarded-Proto": "http",
            },
            json={"platform": "windows"},
        )
    finally:
        settings.app_env, settings.kap_public_base_url = old_env, old_url
    assert response.status_code == 200, response.text
    env = response.json()["mcp_config"]["mcpServers"]["kap"]["env"]
    assert env["KAP_BASE_URL"] == "https://knowledge.example.test"
    assert "attacker.invalid" not in response.text


async def test_production_public_origin_fails_closed_before_rotation(
    client, db_session, monkeypatch
):
    settings = get_settings()
    old_env, old_url = settings.app_env, settings.kap_public_base_url
    settings.app_env = "prod"
    settings.kap_public_base_url = "http://knowledge.example.test/path"
    try:
        with pytest.raises(HTTPException) as exc:
            workbuddy_token_service.public_base_url()
    finally:
        settings.app_env, settings.kap_public_base_url = old_env, old_url
    assert exc.value.status_code == 503
    assert exc.value.detail["denied_reason"] == "workbuddy_public_base_url_invalid"

    def fail_public_origin():
        raise HTTPException(status_code=503, detail=exc.value.detail)

    monkeypatch.setattr(workbuddy_token_service, "public_base_url", fail_public_origin)
    response = await _regen(client)
    assert response.status_code == 503
    rules = (
        (
            await db_session.execute(
                select(AgentWhitelistRule).where(
                    AgentWhitelistRule.agent_identifier == f"workbuddy:self:{USER_CONSULTANT}"
                )
            )
        )
        .scalars()
        .all()
    )
    assert rules == []


async def test_self_service_rule_uses_bound_user_permission_profile(client, db_session):
    response = await _regen(client)
    assert response.status_code == 200
    rule = (
        await db_session.execute(
            select(AgentWhitelistRule).where(
                AgentWhitelistRule.agent_identifier == f"workbuddy:self:{USER_CONSULTANT}"
            )
        )
    ).scalar_one()
    assert rule.bound_user_id == USER_CONSULTANT
    assert rule.is_self_service is True
    assert rule.max_confidentiality_level == "L5"
    assert rule.max_ai_access_level == "A4"


async def test_regenerate_does_not_modify_admin_created_workbuddy_rule(client, db_session):
    managed = AgentWhitelistRule(
        provider="workbuddy",
        agent_identifier=f"workbuddy:self:{USER_CONSULTANT}",
        agent_name="管理员规则",
        capability="qa",
        max_confidentiality_level="L2",
        max_ai_access_level="A2",
        token_hash=hash_token("kgw_admin_managed"),
        enabled=True,
        bound_user_id=USER_CONSULTANT,
    )
    db_session.add(managed)
    await db_session.commit()

    response = await _regen(client)
    assert response.status_code == 409
    assert response.json()["detail"]["denied_reason"] == "workbuddy_managed_rule_exists"
    await db_session.refresh(managed)
    assert managed.agent_identifier == f"workbuddy:self:{USER_CONSULTANT}"
    assert managed.max_confidentiality_level == "L2"
    assert managed.max_ai_access_level == "A2"
    assert managed.is_self_service is False


async def test_regenerate_returns_macos_connector_config(client):
    response = await _regen(client, "macos")
    assert response.status_code == 200, response.text
    kap = response.json()["mcp_config"]["mcpServers"]["kap"]
    assert kap["command"] == (
        "/Applications/KAP WorkBuddy Connector.app/Contents/MacOS/kap-workbuddy-connector"
    )
    assert "python" not in json.dumps(kap).lower()


@pytest.mark.parametrize(
    ("platform", "connector_path"),
    [
        (
            "windows",
            r"D:\Custom Apps\KAP Team\kap-workbuddy-connector.exe",
        ),
        (
            "macos",
            '/Users/example/Custom "Apps"/KAP WorkBuddy Connector.app/'
            "Contents/MacOS/kap-workbuddy-connector",
        ),
    ],
)
async def test_regenerate_uses_custom_connector_path_as_json_text_only(
    client, platform, connector_path
):
    response = await client.post(
        REGEN_URL,
        headers=_dev(USER_CONSULTANT),
        json={"platform": platform, "connector_path": connector_path},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mcp_config"]["mcpServers"]["kap"]["command"] == connector_path
    # JSON encoding must preserve spaces, Windows backslashes and valid POSIX quotes.
    assert json.loads(response.text)["mcp_config"]["mcpServers"]["kap"]["command"] == connector_path


async def test_custom_path_is_not_persisted_or_exposed_after_one_time_response(client, db_session):
    connector_path = r"D:\Private Employee Folder\kap-workbuddy-connector.exe"
    created = await client.post(
        REGEN_URL,
        headers=_dev(USER_CONSULTANT),
        json={"platform": "windows", "connector_path": connector_path},
    )
    assert created.status_code == 200, created.text
    assert created.json()["mcp_config"]["mcpServers"]["kap"]["command"] == connector_path

    status = await client.get(TOKEN_URL, headers=_dev(USER_CONSULTANT))
    assert status.status_code == 200
    assert connector_path not in status.text
    audit_events = (await db_session.execute(select(AuditEvent))).scalars().all()
    audit_blob = json.dumps([event.extra for event in audit_events], ensure_ascii=False)
    assert connector_path not in audit_blob


@pytest.mark.parametrize(
    ("platform", "connector_path"),
    [
        ("windows", "/Applications/KAP/kap-workbuddy-connector"),
        ("windows", r"C:\Apps\kap-workbuddy-connector"),
        ("macos", r"C:\Apps\kap-workbuddy-connector.exe"),
        ("macos", "relative/kap-workbuddy-connector"),
        ("macos", "/Applications/kap-workbuddy-connector.exe"),
        ("macos", "/Applications/KAP\nConnector"),
        ("macos", " /Applications/KAP/kap-workbuddy-connector"),
    ],
)
async def test_invalid_custom_path_fails_before_token_rotation(
    client, db_session, platform, connector_path
):
    response = await client.post(
        REGEN_URL,
        headers=_dev(USER_CONSULTANT),
        json={"platform": platform, "connector_path": connector_path},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["denied_reason"] == "workbuddy_connector_path_invalid"
    rules = (
        (
            await db_session.execute(
                select(AgentWhitelistRule).where(
                    AgentWhitelistRule.agent_identifier == f"workbuddy:self:{USER_CONSULTANT}"
                )
            )
        )
        .scalars()
        .all()
    )
    assert rules == []


@pytest.mark.parametrize("invalid_char", ["<", ">", ":", '"', "/", "|", "?", "*"])
async def test_windows_custom_path_rejects_every_invalid_filename_character(
    client, db_session, invalid_char
):
    connector_path = f"C:\\Apps\\bad{invalid_char}name\\kap-workbuddy-connector.exe"
    response = await client.post(
        REGEN_URL,
        headers=_dev(USER_CONSULTANT),
        json={"platform": "windows", "connector_path": connector_path},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["denied_reason"] == "workbuddy_connector_path_invalid"
    rules = (
        (
            await db_session.execute(
                select(AgentWhitelistRule).where(
                    AgentWhitelistRule.agent_identifier == f"workbuddy:self:{USER_CONSULTANT}"
                )
            )
        )
        .scalars()
        .all()
    )
    assert rules == []


@pytest.mark.parametrize(
    "connector_path",
    [
        r"C:\Apps\trailing.\kap-workbuddy-connector.exe",
        "C:\\Apps\\trailing \\kap-workbuddy-connector.exe",
        r"C:\Apps\CON\kap-workbuddy-connector.exe",
        r"C:\Apps\LPT1.txt\kap-workbuddy-connector.exe",
        r"C:\Apps\\kap-workbuddy-connector.exe",
    ],
)
async def test_windows_custom_path_rejects_invalid_segments(client, db_session, connector_path):
    response = await client.post(
        REGEN_URL,
        headers=_dev(USER_CONSULTANT),
        json={"platform": "windows", "connector_path": connector_path},
    )
    assert response.status_code == 422
    rules = (
        (
            await db_session.execute(
                select(AgentWhitelistRule).where(
                    AgentWhitelistRule.agent_identifier == f"workbuddy:self:{USER_CONSULTANT}"
                )
            )
        )
        .scalars()
        .all()
    )
    assert rules == []


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


def _write_connector_manifest(
    tmp_path,
    monkeypatch,
    *,
    channel="internal",
    signed=False,
    allow_internal=True,
):
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
    settings = get_settings()
    monkeypatch.setattr(settings, "workbuddy_connector_artifact_root", str(root))
    monkeypatch.setattr(settings, "workbuddy_connector_allow_internal", allow_internal)
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


async def test_internal_distribution_requires_explicit_switch_in_every_environment(
    client, tmp_path, monkeypatch
):
    from app.core.config import get_settings

    _write_connector_manifest(
        tmp_path,
        monkeypatch,
        channel="internal",
        signed=False,
        allow_internal=False,
    )
    settings = get_settings()

    local_disabled = await client.get(CONNECTORS_URL, headers=_dev(USER_CONSULTANT))
    assert local_disabled.status_code == 503
    assert (
        local_disabled.json()["detail"]["denied_reason"] == "workbuddy_connector_internal_disabled"
    )

    await client.post(LOGIN, json={"email": BOSS_EMAIL})
    monkeypatch.setattr(settings, "app_env", "prod")

    disabled = await client.get(CONNECTORS_URL)
    assert disabled.status_code == 503
    assert disabled.json()["detail"]["denied_reason"] == "workbuddy_connector_internal_disabled"
    assert "connectors" not in disabled.text

    monkeypatch.setattr(settings, "workbuddy_connector_allow_internal", True)
    enabled = await client.get(CONNECTORS_URL)
    assert enabled.status_code == 200, enabled.text
    assert len(enabled.json()["artifacts"]) == 3
    assert all(
        item["release_status"] == "internal"
        and item["signed"] is False
        and item["notarized"] is False
        for item in enabled.json()["artifacts"]
    )
    download = await client.get(f"{CONNECTORS_URL}/windows/x64/download")
    assert download.status_code == 200

    (tmp_path / "connectors" / "unexpected.txt").write_text(
        "not distributable",
        encoding="utf-8",
    )
    extra = await client.get(CONNECTORS_URL)
    assert extra.status_code == 503
    assert extra.json()["detail"]["denied_reason"] == "workbuddy_connector_unavailable"
    assert "unexpected" not in extra.text


async def test_internal_manifest_cannot_claim_release_signatures(client, tmp_path, monkeypatch):
    from app.core.config import get_settings

    _write_connector_manifest(tmp_path, monkeypatch, channel="internal", signed=True)
    settings = get_settings()
    await client.post(LOGIN, json={"email": BOSS_EMAIL})
    monkeypatch.setattr(settings, "app_env", "prod")
    monkeypatch.setattr(settings, "workbuddy_connector_allow_internal", True)

    response = await client.get(CONNECTORS_URL)
    assert response.status_code == 503
    assert response.json()["detail"]["denied_reason"] == "workbuddy_connector_unavailable"
    assert "signed" not in response.text and "notarized" not in response.text


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
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "prod")
    monkeypatch.setattr(settings, "workbuddy_connector_allow_internal", True)
    response = await client.get(CONNECTORS_URL)
    assert response.status_code == 503
    assert response.json()["detail"]["denied_reason"] == "workbuddy_connector_unsigned"

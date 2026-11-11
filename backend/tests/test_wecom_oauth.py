"""OAuth regression: fake clients only; scanning is retired."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.main import app
from app.models.audit import AuditEvent
from app.models.identity import User
from app.seed.dev_seed import (
    USER_CONSULTANT,
)
from app.services.wecom_client import (
    WeComError,
    WeComIdentity,
    get_wecom_oauth_client,
)

START = "/api/v1/auth/wecom/start"
CALLBACK = "/api/v1/auth/wecom/callback"

_LEAK = [
    "source_file_ref",
    "storage_ref",
    "internal://",
    "download_url",
    "access_token",
    "app_secret",
    "wecom_secret",
    "ww_consultant_a",
    "weknora",
    "kb_id",
    "doc_id",
    "sk-",
    "Bearer",
]


def _assert_no_leak(text):
    for t in _LEAK:
        assert t not in text, f"响应不应泄露 {t}"


class FakeOAuth:
    def __init__(self, wecom_user_id="ww_consultant_a"):
        self.wecom_user_id = wecom_user_id

    def build_authorize_url(self, *, state, mode="client"):
        # 含 corp_id/state，绝不含 app_secret。
        base = (
            "https://open.work.weixin.qq.com/wwopen/sso/qrConnect"
            if mode == "web_qr"
            else "https://open.weixin.qq.com/connect/oauth2/authorize"
        )
        return f"{base}?appid=test_corp&state={state}"

    async def exchange_code(self, code):
        if not code:
            raise WeComError("wecom_missing_code", "缺少 code")
        return WeComIdentity(wecom_user_id=self.wecom_user_id)

    async def get_member_status(self, wecom_user_id):
        # 默认 fake 成员有效（保持既有回调成功用例语义）。
        from app.services.wecom_client import WeComMemberStatus

        return WeComMemberStatus(wecom_user_id, True, "active", "企微成员有效")


def _install_oauth(fake):
    app.dependency_overrides[get_wecom_oauth_client] = lambda: fake


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.pop(get_wecom_oauth_client, None)


# ---------------- OAuth ----------------
async def test_oauth_start_state_bound_no_secret(client):
    _install_oauth(FakeOAuth())
    resp = await client.get(START)
    assert resp.status_code == 200
    url = resp.json()["authorize_url"]
    assert "connect/oauth2/authorize" in url
    assert "state=" in url and "appid=" in url
    assert "secret" not in resp.text
    # state 写入 httpOnly cookie（不在 JSON body）。
    assert client.cookies.get("kap_oauth_state")


async def test_oauth_start_web_qr_state_bound_no_secret(client):
    _install_oauth(FakeOAuth())
    resp = await client.get(START, params={"mode": "web_qr"})
    assert resp.status_code == 200
    url = resp.json()["authorize_url"]
    assert "wwopen/sso/qrConnect" in url
    assert "state=" in url and "appid=" in url
    assert "secret" not in resp.text
    # state 写入 httpOnly cookie（不在 JSON body）。
    assert client.cookies.get("kap_oauth_state")


async def test_oauth_callback_success_creates_session(client):
    _install_oauth(FakeOAuth("ww_consultant_a"))
    await client.get(START)
    state = client.cookies.get("kap_oauth_state")
    resp = await client.get(
        CALLBACK,
        params={"code": "valid-code", "state": state},
        headers={"X-Trace-Id": "trc-oauth-ok"},
    )
    assert resp.status_code == 303, resp.text
    assert resp.headers["location"] == "/"
    assert "kap_session=" in resp.headers.get("set-cookie", "")
    assert resp.text == ""
    # 会话 cookie 已下发；后续 /auth/me 即为该用户。
    me = await client.get("/api/v1/auth/me")
    assert me.json()["user_id"] == str(USER_CONSULTANT)
    _assert_no_leak(resp.text)


async def test_oauth_callback_unknown_user_fails_closed(client):
    _install_oauth(FakeOAuth("ww_unknown_nobody"))
    await client.get(START)
    state = client.cookies.get("kap_oauth_state")
    resp = await client.get(CALLBACK, params={"code": "c", "state": state})
    assert resp.status_code == 303, resp.text
    body = (await client.get("/api/v1/auth/me")).json()
    assert body["status"] == "active"
    assert body["company_roles"] == ["consultant"]
    assert body["is_business_user"] is True
    assert body["can_discover_l5"] is False


async def test_oauth_callback_inactive_user_fails_closed(client, db_session):
    inactive = User(
        id=uuid.uuid4(),
        name="离职X",
        email="left@dev.local",
        status="inactive",
        wecom_user_id="ww_inactive",
    )
    db_session.add(inactive)
    await db_session.commit()
    _install_oauth(FakeOAuth("ww_inactive"))
    await client.get(START)
    state = client.cookies.get("kap_oauth_state")
    resp = await client.get(
        CALLBACK, params={"code": "c", "state": state}, headers={"X-Trace-Id": "trc-oauth-inactive"}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"]["denied_reason"] == "user_inactive"


async def test_oauth_callback_invalid_state_rejected(client):
    _install_oauth(FakeOAuth())
    await client.get(START)  # sets a state cookie
    # 提供不匹配的 state → 400。
    resp = await client.get(CALLBACK, params={"code": "c", "state": "tampered-state"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["denied_reason"] == "oauth_state_invalid"


async def test_oauth_audit_has_no_code_or_token(client, db_session):
    _install_oauth(FakeOAuth("ww_consultant_a"))
    await client.get(START)
    state = client.cookies.get("kap_oauth_state")
    await client.get(
        CALLBACK,
        params={"code": "secret-code-xyz", "state": state},
        headers={"X-Trace-Id": "trc-oauth-audit"},
    )
    row = (
        await db_session.execute(
            select(AuditEvent)
            .where(AuditEvent.trace_id == "trc-oauth-audit")
            .where(AuditEvent.action == "auth.wecom_login_success")
        )
    ).scalar_one()
    extra_text = str(row.extra or {})
    assert row.extra.get("login_method") == "wecom_oauth"
    for tok in ("secret-code-xyz", "access_token", "code", "state"):
        assert tok not in extra_text

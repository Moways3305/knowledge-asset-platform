"""PBC-41 企微 OAuth 自动开户与身份同步。

覆盖：服务端 code 交换身份为唯一信任源；有效企微成员自动创建低权限用户；现有用户安全同步；
同名/邮箱不参与登录归并；失效成员 fail closed；审计与响应不泄露 code/token/raw userid。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.main import app
from app.models.audit import AuditEvent
from app.models.identity import User, UserCompanyRole
from app.seed.dev_seed import USER_ADMIN_ONLY
from app.services.wecom_client import (
    WeComError,
    WeComIdentity,
    WeComMemberStatus,
    get_wecom_oauth_client,
)

START = "/api/v1/auth/wecom/start"
CALLBACK = "/api/v1/auth/wecom/callback"
PEOPLE = "/api/v1/admin/people"


class FakeOAuth:
    corp_id = "corp-a"

    def __init__(self, *, user_id="ww_new", member=None, error=None):
        self.user_id = user_id
        self.member = member
        self.error = error
        self.exchanged_codes: list[str] = []
        self.status_calls: list[str] = []

    def build_authorize_url(self, *, state, mode="client"):
        base = (
            "https://open.work.weixin.qq.com/wwopen/sso/qrConnect"
            if mode == "web_qr"
            else "https://open.weixin.qq.com/connect/oauth2/authorize"
        )
        return f"{base}?appid=corp-a&state={state}"

    async def exchange_code(self, code):
        self.exchanged_codes.append(code)
        return WeComIdentity(wecom_user_id=self.user_id)

    async def get_member_status(self, wecom_user_id):
        self.status_calls.append(wecom_user_id)
        if self.error:
            raise self.error
        return self.member or WeComMemberStatus(
            wecom_user_id,
            True,
            "active",
            "企微成员有效",
            name="企微新人",
            email="new.user@corp.example",
            avatar="https://avatar.example/u.png",
            department_ids=("10", "20"),
        )


def _install(fake):
    app.dependency_overrides[get_wecom_oauth_client] = lambda: fake


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.pop(get_wecom_oauth_client, None)


async def _callback(client, fake, *, code="server-code", extra_params=None, trace="trc-wecom"):
    _install(fake)
    await client.get(START)
    state = client.cookies.get("kap_oauth_state")
    params = {"code": code, "state": state}
    params.update(extra_params or {})
    return await client.get(CALLBACK, params=params, headers={"X-Trace-Id": trace})


def _admin_headers():
    return {"X-Dev-User-Id": str(USER_ADMIN_ONLY)}


async def test_valid_wecom_member_auto_creates_active_consultant(client, db_session):
    r = await _callback(client, FakeOAuth())
    assert r.status_code == 303, r.text
    assert r.headers["location"] == "/"
    assert "kap_session=" in r.headers.get("set-cookie", "")
    body = (await client.get("/api/v1/auth/me")).json()
    assert body["name"] == "企微新人"
    assert body["email"] == "new.user@corp.example"
    assert body["status"] == "active"
    assert body["company_roles"] == ["consultant"]
    assert body["project_memberships"] == []
    assert body["is_business_user"] is True
    assert body["can_discover_l5"] is False

    user = (
        await db_session.execute(select(User).where(User.email == "new.user@corp.example"))
    ).scalar_one()
    assert user.wecom_corp_id == "corp-a"
    assert user.wecom_user_id == "ww_new"
    assert user.wecom_name == "企微新人"
    assert user.wecom_email == "new.user@corp.example"
    assert user.last_login_at is not None
    roles = (
        await db_session.execute(
            select(UserCompanyRole.company_role, UserCompanyRole.status).where(
                UserCompanyRole.user_id == user.id
            )
        )
    ).all()
    assert roles == [("consultant", "active")]


async def test_frontend_self_reported_identity_is_ignored(client, db_session):
    fake = FakeOAuth(user_id="ww_server_truth")
    r = await _callback(
        client,
        fake,
        extra_params={
            "wecom_user_id": "ww_attacker",
            "email": "admin.e@dev.local",
            "name": "管理员E",
        },
    )
    assert r.status_code == 303, r.text
    assert fake.exchanged_codes == ["server-code"]
    assert fake.status_calls == ["ww_server_truth"]
    assert (
        await db_session.execute(select(User).where(User.wecom_user_id == "ww_attacker"))
    ).scalar_one_or_none() is None
    created = (
        await db_session.execute(select(User).where(User.wecom_user_id == "ww_server_truth"))
    ).scalar_one()
    assert created.email == "new.user@corp.example"


async def test_callback_success_ignores_open_redirect_attempt(client):
    r = await _callback(
        client,
        FakeOAuth(user_id="ww_redirect"),
        extra_params={"next": "https://evil.example/callback", "redirect": "//evil.example"},
    )
    assert r.status_code == 303, r.text
    assert r.headers["location"] == "/"
    assert "evil.example" not in r.headers["location"]
    assert "evil.example" not in r.text


async def test_same_name_user_is_not_confused(client, db_session):
    existing = User(
        id=uuid.uuid4(),
        name="企微新人",
        email="same-name@dev.local",
        status="active",
    )
    existing.company_roles.append(UserCompanyRole(company_role="boss", status="active"))
    db_session.add(existing)
    await db_session.commit()

    r = await _callback(client, FakeOAuth(user_id="ww_same_name"))
    assert r.status_code == 303, r.text
    assert (await client.get("/api/v1/auth/me")).json()["user_id"] != str(existing.id)
    unchanged = await db_session.get(User, existing.id)
    assert unchanged.wecom_user_id is None


async def test_existing_user_sync_does_not_overwrite_email_with_empty(client, db_session):
    uid = uuid.uuid4()
    user = User(
        id=uid,
        name="旧名",
        email="keep@corp.example",
        status="active",
        wecom_corp_id="corp-a",
        wecom_user_id="ww_existing",
    )
    user.company_roles.append(UserCompanyRole(company_role="consultant", status="active"))
    db_session.add(user)
    await db_session.commit()

    member = WeComMemberStatus("ww_existing", True, "active", "企微成员有效", name="新名", email="")
    r = await _callback(client, FakeOAuth(user_id="ww_existing", member=member))
    assert r.status_code == 303, r.text
    refreshed = await db_session.get(User, uid)
    await db_session.refresh(refreshed)
    assert refreshed.name == "新名"
    assert refreshed.email == "keep@corp.example"
    assert refreshed.wecom_email is None
    assert refreshed.wecom_synced_at is not None


async def test_inactive_wecom_member_fails_safely_without_auto_create(client, db_session):
    fake = FakeOAuth(
        user_id="ww_disabled",
        member=WeComMemberStatus("ww_disabled", False, "disabled", "企微成员已禁用"),
    )
    r = await _callback(client, fake)
    assert r.status_code == 401
    assert r.json()["detail"]["denied_reason"] == "wecom_user_inactive"
    assert "ww_disabled" not in r.text
    assert (
        await db_session.execute(select(User).where(User.wecom_user_id == "ww_disabled"))
    ).scalar_one_or_none() is None


async def test_upstream_error_fails_safely_and_audit_has_no_leaks(client, db_session):
    r = await _callback(
        client,
        FakeOAuth(user_id="ww_secret", error=WeComError("wecom_forbidden", "raw errmsg")),
        code="oauth-code-secret",
        trace="trc-wecom-denied",
    )
    assert r.status_code == 401
    blob = r.text
    for token in ("oauth-code-secret", "ww_secret", "access_token", "raw errmsg"):
        assert token not in blob
    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.trace_id == "trc-wecom-denied")
            )
        )
        .scalars()
        .all()
    )
    assert [e.action for e in events] == ["auth.wecom_login_denied"]
    audit_blob = str([e.extra for e in events])
    for token in ("oauth-code-secret", "ww_secret", "access_token", "raw errmsg", "state"):
        assert token not in audit_blob
    assert events[0].extra["reason"] == "wecom_status_check_failed"


async def test_state_and_code_rejections_write_safe_denied_audit(client, db_session):
    fake = FakeOAuth()
    _install(fake)
    await client.get(START)
    state = client.cookies.get("kap_oauth_state")

    bad_state = await client.get(
        CALLBACK,
        params={"code": "code-should-not-leak", "state": "tampered-state"},
        headers={"X-Trace-Id": "trc-state-denied"},
    )
    assert bad_state.status_code == 400
    assert bad_state.json()["detail"]["denied_reason"] == "oauth_state_invalid"
    assert fake.exchanged_codes == []

    await client.get(START)
    state = client.cookies.get("kap_oauth_state")
    missing_code = await client.get(
        CALLBACK,
        params={"state": state},
        headers={"X-Trace-Id": "trc-code-denied"},
    )
    assert missing_code.status_code == 400
    assert missing_code.json()["detail"]["denied_reason"] == "oauth_code_missing"

    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.trace_id.in_(["trc-state-denied", "trc-code-denied"])
                )
            )
        )
        .scalars()
        .all()
    )
    assert {e.action for e in events} == {"auth.wecom_login_denied"}
    assert {e.actor_user_id for e in events} == {None}
    assert {e.extra["reason"] for e in events} == {"oauth_state_invalid", "oauth_code_missing"}
    audit_blob = str([e.extra for e in events])
    for token in ("code-should-not-leak", "tampered-state", state or ""):
        if token:
            assert token not in audit_blob


async def test_people_list_can_see_auto_created_user_without_wecom_id_leak(client):
    r = await _callback(client, FakeOAuth(user_id="ww_people"))
    assert r.status_code == 303, r.text
    created_id = (await client.get("/api/v1/auth/me")).json()["user_id"]
    client.cookies.clear()
    people = await client.get(PEOPLE, headers=_admin_headers(), params={"q": "企微新人"})
    assert people.status_code == 200, people.text
    item = next(i for i in people.json()["items"] if i["user_id"] == created_id)
    assert item["wecom_bound"] is True
    assert "wecom_user_id" not in item
    assert "ww_people" not in people.text

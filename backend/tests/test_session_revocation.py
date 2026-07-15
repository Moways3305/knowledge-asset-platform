"""平台会话撤销测试。

覆盖：
- admin 可查看某用户安全会话元数据；boss/director/consultant/pm 403；
- 响应无 token / token_hash / cookie / OAuth state / password·hash·salt·digest / raw IP；
- admin 手动撤销使目标用户活动会话失效；
- 用户停用 / 改密联动撤销活动会话；
- 撤销 POST 无 CSRF → 403 且不写审计；有 CSRF → 成功；
- 审计 extra 仅 counts / trigger / reason / target_user_id。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.audit import AuditEvent
from app.seed.dev_seed import (
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
    USER_PROJECT_MANAGER,
)

LOGIN = "/api/v1/auth/login"
CSRF = "/api/v1/auth/csrf"
CONSULTANT_EMAIL = "consultant.a@dev.local"
ADMIN_EMAIL = "admin.e@dev.local"

_LEAK = [
    "token_hash",
    "kap_session",
    "kap_oauth_state",
    "password_hash",
    "salt",
    "digest",
    "pbkdf2",
    "device_info",
    "user-agent",
    "127.0.0.1",
]


def _hdr(uid):
    return {"X-Dev-User-Id": str(uid)}


def _sessions_url(uid):
    return f"/admin/ops/sessions/users/{uid}"


def _revoke_url(uid):
    return f"/admin/ops/sessions/users/{uid}/revoke"


async def _login_target_then_drop_cookie(client, email):
    """以目标用户登录建一条平台会话，然后清掉 client cookie jar（后续以 admin dev 头操作）。"""
    r = await client.post(LOGIN, json={"email": email})
    assert r.status_code == 200, r.text
    client.cookies.clear()


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------
async def test_admin_can_list_sessions(client):
    await _login_target_then_drop_cookie(client, CONSULTANT_EMAIL)
    r = await client.get(_sessions_url(USER_CONSULTANT), headers=_hdr(USER_ADMIN_ONLY))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_id"] == str(USER_CONSULTANT)
    assert body["active_count"] >= 1
    assert body["sessions"] and "session_id" in body["sessions"][0]


@pytest.mark.parametrize("uid", [USER_BOSS, USER_DIRECTOR, USER_CONSULTANT, USER_PROJECT_MANAGER])
async def test_list_sessions_forbidden_non_admin(client, uid):
    r = await client.get(_sessions_url(USER_CONSULTANT), headers=_hdr(uid))
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "ops_admin_required"


async def test_revoke_forbidden_non_admin(client):
    r = await client.post(_revoke_url(USER_CONSULTANT), headers=_hdr(USER_BOSS), json={})
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "ops_admin_required"


# ---------------------------------------------------------------------------
# no-leak
# ---------------------------------------------------------------------------
async def test_sessions_response_no_leak(client):
    await _login_target_then_drop_cookie(client, CONSULTANT_EMAIL)
    r = await client.get(_sessions_url(USER_CONSULTANT), headers=_hdr(USER_ADMIN_ONLY))
    assert r.status_code == 200
    for t in _LEAK:
        assert t not in r.text, t


# ---------------------------------------------------------------------------
# 手动撤销
# ---------------------------------------------------------------------------
async def test_admin_manual_revoke_invalidates_sessions(client, db_session):
    await _login_target_then_drop_cookie(client, CONSULTANT_EMAIL)
    r = await client.post(
        _revoke_url(USER_CONSULTANT),
        headers=_hdr(USER_ADMIN_ONLY),
        json={"reason": "force offline"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["revoked_count"] >= 1 and body["revoked_at"]
    # 再查 → 无活动会话。
    after = await client.get(_sessions_url(USER_CONSULTANT), headers=_hdr(USER_ADMIN_ONLY))
    assert after.json()["active_count"] == 0
    # 审计安全。
    ev = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "auth.sessions_revoked")
            )
        )
        .scalars()
        .all()
    )
    assert ev
    extra = ev[0].extra or {}
    assert extra.get("trigger") == "admin_manual"
    assert extra.get("target_user_id") == str(USER_CONSULTANT)
    assert "revoked_count" in extra
    blob = str([(e.extra, e.before_snapshot, e.after_snapshot) for e in ev])
    for t in _LEAK:
        assert t not in blob


# ---------------------------------------------------------------------------
# 自动撤销：停用
# ---------------------------------------------------------------------------
async def test_deactivation_revokes_sessions(client, db_session):
    await _login_target_then_drop_cookie(client, CONSULTANT_EMAIL)
    r = await client.post(
        f"/api/v1/admin/people/{USER_CONSULTANT}/status",
        headers=_hdr(USER_BOSS),
        json={"status": "inactive"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "inactive"
    assert r.json()["active_session_count"] == 0
    # 联动审计 trigger=user_deactivated。
    ev = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "auth.sessions_revoked")
            )
        )
        .scalars()
        .all()
    )
    assert any((e.extra or {}).get("trigger") == "user_deactivated" for e in ev)


async def test_admin_cannot_use_people_status_endpoint(client):
    r = await client.post(
        f"/api/v1/admin/people/{USER_ADMIN_ONLY}/status",
        headers=_hdr(USER_ADMIN_ONLY),
        json={"status": "inactive"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "admin_business_permission_denied"


async def test_status_endpoint_governance_allowed(client):
    r = await client.post(
        f"/api/v1/admin/people/{USER_CONSULTANT}/status",
        headers=_hdr(USER_BOSS),
        json={"status": "inactive"},
    )
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# 自动撤销：改密
# ---------------------------------------------------------------------------
async def test_password_reset_revokes_sessions(client, db_session):
    await _login_target_then_drop_cookie(client, CONSULTANT_EMAIL)
    r = await client.post(
        f"/api/v1/admin/people/{USER_CONSULTANT}/password",
        headers=_hdr(USER_BOSS),
        json={"password": "newpass1234"},
    )
    assert r.status_code == 200, r.text
    after = await client.get(_sessions_url(USER_CONSULTANT), headers=_hdr(USER_ADMIN_ONLY))
    assert after.json()["active_count"] == 0
    ev = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "auth.sessions_revoked")
            )
        )
        .scalars()
        .all()
    )
    assert any((e.extra or {}).get("trigger") == "password_reset" for e in ev)


# ---------------------------------------------------------------------------
# CSRF 覆盖撤销 POST
# ---------------------------------------------------------------------------
async def test_revoke_without_csrf_forbidden_no_audit(client, db_session):
    await client.post(LOGIN, json={"email": ADMIN_EMAIL})  # admin cookie 会话
    r = await client.post(_revoke_url(USER_CONSULTANT), json={})  # 无 X-CSRF-Token
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "csrf_token_missing"
    ev = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "auth.sessions_revoked")
            )
        )
        .scalars()
        .all()
    )
    assert ev == []


async def test_revoke_with_csrf_succeeds(client):
    await client.post(LOGIN, json={"email": ADMIN_EMAIL})
    csrf = (await client.get(CSRF)).json()["csrf_token"]
    r = await client.post(_revoke_url(USER_CONSULTANT), headers={"X-CSRF-Token": csrf}, json={})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


# ---------------------------------------------------------------------------
# 保留当前会话（self 强制下线其它会话）
# ---------------------------------------------------------------------------
async def test_preserve_current_session_keeps_admin_logged_in(client):
    await client.post(LOGIN, json={"email": ADMIN_EMAIL})  # admin 会话 A
    csrf = (await client.get(CSRF)).json()["csrf_token"]
    # admin 撤销自己的会话但保留当前 → 当前会话仍可用（active_count 不为 0）。
    r = await client.post(
        _revoke_url(USER_ADMIN_ONLY),
        headers={"X-CSRF-Token": csrf},
        json={"preserve_current_session": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["preserved_current_session"] is True
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["email"] == ADMIN_EMAIL

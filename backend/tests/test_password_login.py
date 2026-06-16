"""密码凭证登录 + 管理员设置密码测试。

覆盖：prod email+password 成功 / email-only 拒绝；错密码·未知 email·未设密码·inactive 统一 401；
登录审计 login_method；admin 设置/重置密码、非 admin 拒绝、弱密码 422、重置后旧密码失效；
dev_local 仍可用；people 只回 password_set/password_set_at；无 password/hash/salt/token 泄露。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.models.audit import AuditEvent
from app.seed.dev_seed import (
    DEV_PASSWORD,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
)
from app.services import passwords

LOGIN = "/api/v1/auth/login"
PEOPLE = "/api/v1/admin/people"
BOSS_EMAIL = "boss.c@dev.local"
CONSULTANT_EMAIL = "consultant.a@dev.local"


def _hdr(u):
    return {"X-Dev-User-Id": str(u)}


def _prod(monkeypatch):
    monkeypatch.setattr("app.api.auth.get_settings", lambda: Settings(app_env="prod"))


async def _csrf(client):
    """取一条绑定当前会话 cookie 的 CSRF token。"""
    r = await client.get("/api/v1/auth/csrf")
    return {"X-CSRF-Token": r.json()["csrf_token"]}


# ---------------------------------------------------------------------------
# 密码哈希服务单元
# ---------------------------------------------------------------------------
def test_password_hash_roundtrip():
    enc = passwords.hash_password("hunter2pw")
    assert enc.startswith("pbkdf2_sha256$")
    assert passwords.verify_password("hunter2pw", enc) is True
    assert passwords.verify_password("wrong", enc) is False
    # 编码里不含明文密码。
    assert "hunter2pw" not in enc


def test_password_verify_safe_on_bad_input():
    assert passwords.verify_password("x", None) is False
    assert passwords.verify_password("x", "") is False
    assert passwords.verify_password("x", "not-a-valid-hash") is False
    assert passwords.verify_password("x", "unknownalg$1$a$b") is False
    assert passwords.verify_password("", passwords.hash_password("abc12345")) is False


def test_password_strength():
    assert passwords.validate_password_strength("short") is not None
    assert passwords.validate_password_strength("        ") is not None
    assert passwords.validate_password_strength("longenough1") is None


# ---------------------------------------------------------------------------
# prod 登录矩阵
# ---------------------------------------------------------------------------
async def test_prod_password_login_success(client, monkeypatch):
    _prod(monkeypatch)
    r = await client.post(LOGIN, json={"email": BOSS_EMAIL, "password": DEV_PASSWORD})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == BOSS_EMAIL
    # 明文凭证 / hash / token 不进 JSON；cookie 下发。
    for token in [DEV_PASSWORD, "password_hash", "salt", "digest", "pbkdf2", "kap_session"]:
        assert token not in r.text
    assert "kap_session=" in r.headers.get("set-cookie", "")


async def test_prod_email_only_rejected(client, monkeypatch):
    _prod(monkeypatch)
    r = await client.post(LOGIN, json={"email": BOSS_EMAIL})
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "auth_password_required"


async def test_prod_wrong_password_401(client, monkeypatch):
    _prod(monkeypatch)
    r = await client.post(LOGIN, json={"email": BOSS_EMAIL, "password": "definitely-wrong"})
    assert r.status_code == 401
    assert r.json()["detail"]["denied_reason"] == "invalid_credentials"


async def test_prod_unknown_email_401(client, monkeypatch):
    _prod(monkeypatch)
    r = await client.post(LOGIN, json={"email": "nobody@dev.local", "password": DEV_PASSWORD})
    assert r.status_code == 401
    assert r.json()["detail"]["denied_reason"] == "invalid_credentials"


async def test_prod_no_password_set_401(client, db_session, monkeypatch):
    # 把某用户密码清空 → 即使提供密码也统一 401。
    from app.models.identity import User

    u = (await db_session.execute(select(User).where(User.id == USER_CONSULTANT))).scalar_one()
    u.password_hash = None
    await db_session.commit()
    _prod(monkeypatch)
    r = await client.post(LOGIN, json={"email": CONSULTANT_EMAIL, "password": DEV_PASSWORD})
    assert r.status_code == 401
    assert r.json()["detail"]["denied_reason"] == "invalid_credentials"


async def test_prod_inactive_user_401(client, db_session, monkeypatch):
    from app.models.identity import User

    u = (await db_session.execute(select(User).where(User.id == USER_CONSULTANT))).scalar_one()
    u.status = "inactive"
    await db_session.commit()
    _prod(monkeypatch)
    r = await client.post(LOGIN, json={"email": CONSULTANT_EMAIL, "password": DEV_PASSWORD})
    assert r.status_code == 401
    assert r.json()["detail"]["denied_reason"] == "invalid_credentials"


# ---------------------------------------------------------------------------
# 登录审计
# ---------------------------------------------------------------------------
async def test_login_success_audit_method_password(client, db_session, monkeypatch):
    _prod(monkeypatch)
    await client.post(LOGIN, json={"email": BOSS_EMAIL, "password": DEV_PASSWORD})
    ev = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.action == "login.success")))
        .scalars()
        .all()
    )
    assert any((e.extra or {}).get("login_method") == "password" for e in ev)
    blob = str([(e.extra, e.actor_user_id) for e in ev])
    # 注：login_method 值即 "password"（安全字段名值）；只校验真实凭证不泄露。
    for token in [DEV_PASSWORD, "password_hash", "salt", "digest", "pbkdf2", "kap_session"]:
        assert token not in blob


async def test_known_user_failure_audited_no_leak(client, db_session, monkeypatch):
    _prod(monkeypatch)
    await client.post(LOGIN, json={"email": BOSS_EMAIL, "password": "wrong-one"})
    ev = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.action == "login.failed")))
        .scalars()
        .all()
    )
    assert len(ev) >= 1
    blob = str([(e.extra, e.before_snapshot, e.after_snapshot) for e in ev])
    for token in ["wrong-one", "password_hash", "salt", "digest", "kap_session"]:
        assert token not in blob


async def test_unknown_email_failure_not_audited_as_actor(client, db_session, monkeypatch):
    _prod(monkeypatch)
    await client.post(LOGIN, json={"email": "ghost@dev.local", "password": "whatever"})
    ev = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.action == "login.failed")))
        .scalars()
        .all()
    )
    # 未知 email 不写**可归属** login.failed；改记 actor=None 的系统安全事件
    # （仅不可逆 hash 前缀 + reason_code，无 raw email）。
    assert all(e.actor_user_id is None for e in ev)
    assert "ghost@dev.local" not in str([e.extra for e in ev])


# ---------------------------------------------------------------------------
# 登出审计 login_method 真实化
# ---------------------------------------------------------------------------
LOGOUT = "/api/v1/auth/logout"


async def _logout_method(db_session):
    ev = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.action == "login.logout")))
        .scalars()
        .all()
    )
    return ev


async def test_logout_audit_login_method_password(client, db_session, monkeypatch):
    _prod(monkeypatch)
    li = await client.post(LOGIN, json={"email": BOSS_EMAIL, "password": DEV_PASSWORD})
    assert li.status_code == 200
    lo = await client.post(
        LOGOUT, headers=await _csrf(client)
    )  # 同一 client 携带 kap_session cookie
    assert lo.status_code == 200 and lo.json()["ok"] is True
    ev = await _logout_method(db_session)
    assert any((e.extra or {}).get("login_method") == "password" for e in ev)
    # 登出响应与审计不含明文 token / token_hash / cookie 值。
    blob = str([e.extra for e in ev])
    for token in ["kap_session", "token_hash", DEV_PASSWORD]:
        assert token not in blob and token not in lo.text


async def test_logout_audit_login_method_dev_local(client, db_session):
    li = await client.post(LOGIN, json={"email": BOSS_EMAIL})  # test 环境 email-only → dev_local
    assert li.status_code == 200
    lo = await client.post(LOGOUT, headers=await _csrf(client))
    assert lo.status_code == 200
    ev = await _logout_method(db_session)
    assert any((e.extra or {}).get("login_method") == "dev_local" for e in ev)


# ---------------------------------------------------------------------------
# dev_local 仍可用
# ---------------------------------------------------------------------------
async def test_dev_local_email_only_still_works(client):
    # 默认 test 环境：email-only 走 dev adapter，login_method=dev_local。
    r = await client.post(LOGIN, json={"email": BOSS_EMAIL})
    assert r.status_code == 200, r.text
    assert "kap_session=" in r.headers.get("set-cookie", "")


# ---------------------------------------------------------------------------
# admin 设置 / 重置密码
# ---------------------------------------------------------------------------
async def test_admin_sets_password_then_login(client, monkeypatch):
    r = await client.post(
        f"{PEOPLE}/{USER_CONSULTANT}/password",
        headers=_hdr(USER_ADMIN_ONLY),
        json={"password": "newpass1234"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["password_set"] is True
    for token in ["newpass1234", "hash", "salt", "digest"]:
        assert token not in r.text
    # 新密码可登录、旧密码失效（prod）。
    _prod(monkeypatch)
    ok = await client.post(LOGIN, json={"email": CONSULTANT_EMAIL, "password": "newpass1234"})
    assert ok.status_code == 200
    old = await client.post(LOGIN, json={"email": CONSULTANT_EMAIL, "password": DEV_PASSWORD})
    assert old.status_code == 401


@pytest.mark.parametrize("user", [USER_BOSS, USER_CONSULTANT])
async def test_non_admin_cannot_set_password(client, user):
    r = await client.post(
        f"{PEOPLE}/{USER_CONSULTANT}/password", headers=_hdr(user), json={"password": "newpass1234"}
    )
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "password_set_admin_required"


async def test_set_weak_password_422(client):
    r = await client.post(
        f"{PEOPLE}/{USER_CONSULTANT}/password",
        headers=_hdr(USER_ADMIN_ONLY),
        json={"password": "short"},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["denied_reason"] == "weak_password"


async def test_set_password_unknown_user_404(client):
    import uuid as _uuid

    r = await client.post(
        f"{PEOPLE}/{_uuid.uuid4()}/password",
        headers=_hdr(USER_ADMIN_ONLY),
        json={"password": "newpass1234"},
    )
    assert r.status_code == 404


async def test_password_set_audit_safe(client, db_session):
    await client.post(
        f"{PEOPLE}/{USER_CONSULTANT}/password",
        headers=_hdr(USER_ADMIN_ONLY),
        json={"password": "auditpass123"},
    )
    ev = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "auth.password_set")
            )
        )
        .scalars()
        .all()
    )
    assert len(ev) >= 1
    assert any((e.extra or {}).get("password_set") is True for e in ev)
    blob = str([(e.extra, e.before_snapshot, e.after_snapshot) for e in ev])
    for token in ["auditpass123", "password_hash", "salt", "digest", "pbkdf2"]:
        assert token not in blob


# ---------------------------------------------------------------------------
# people 安全字段
# ---------------------------------------------------------------------------
async def test_people_returns_only_safe_password_fields(client):
    d = await client.get(f"{PEOPLE}/{USER_CONSULTANT}", headers=_hdr(USER_ADMIN_ONLY))
    assert d.status_code == 200
    body = d.json()
    assert body["password_set"] is True
    assert "password_set_at" in body
    for token in ["password_hash", "salt", "digest", "pbkdf2", DEV_PASSWORD]:
        assert token not in d.text
    lst = await client.get(PEOPLE, headers=_hdr(USER_ADMIN_ONLY))
    for token in ["password_hash", "salt", "digest", "pbkdf2"]:
        assert token not in lst.text

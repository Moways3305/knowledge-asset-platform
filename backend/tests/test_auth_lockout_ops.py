"""登录风控运维 + 手动解锁测试。

覆盖：
- admin 可查看 auth-security 聚合；boss/director/consultant/pm 403；
- 响应无 raw email / raw IP / 完整 hash / password·hash·salt·digest / token / cookie；
- 已知用户锁定后 admin 用 user_id 解锁 → 正确密码可登录；
- 解锁不重置 IP rate limit；
- identifier_hash_prefix 唯一可解锁；不存在 404；多匹配 409；过短 422；
- 解锁写 auth.lockout_unlocked 审计，extra 安全；
- 无 CSRF 的解锁 POST 403 且不写审计；有 CSRF 成功。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.models.audit import AuditEvent
from app.models.auth_security import AuthLoginAttempt
from app.seed.dev_seed import (
    DEV_PASSWORD,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
    USER_PROJECT_MANAGER,
)
from app.services import auth_security

LOGIN = "/api/v1/auth/login"
OVERVIEW = "/admin/ops/auth-security"
UNLOCK = "/admin/ops/auth-security/unlock"
CSRF = "/api/v1/auth/csrf"
CONSULTANT_EMAIL = "consultant.a@dev.local"
ADMIN_EMAIL = "admin.e@dev.local"

_LEAK = ["password_hash", "salt", "digest", "pbkdf2", "kap_session", "token_hash",
         "kap_oauth_state", "secret.txt"]


def _hdr(uid):
    return {"X-Dev-User-Id": str(uid)}


def _id_hash(email):
    return auth_security.hash_login_identifier(
        auth_security.normalize_login_identifier(email), purpose="identifier"
    )


async def _fail_logins(client, email, n, monkeypatch=None, max_failed=3):
    if monkeypatch is not None:
        monkeypatch.setattr(
            "app.api.auth.get_settings",
            lambda: Settings(app_env="test", auth_max_failed_attempts=max_failed),
        )
    for _ in range(n):
        r = await client.post(LOGIN, json={"email": email, "password": "wrong-pw"})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------
async def test_overview_admin_ok(client):
    r = await client.get(OVERVIEW, headers=_hdr(USER_ADMIN_ONLY))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "counts" in body and "recent_events" in body
    assert set(["failed", "locked", "rate_limited", "success", "unlocked"]).issubset(body["counts"].keys())


@pytest.mark.parametrize("uid", [USER_BOSS, USER_DIRECTOR, USER_CONSULTANT, USER_PROJECT_MANAGER])
async def test_overview_forbidden_for_non_admin(client, uid):
    r = await client.get(OVERVIEW, headers=_hdr(uid))
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "ops_admin_required"


async def test_unlock_forbidden_for_non_admin(client):
    r = await client.post(UNLOCK, headers=_hdr(USER_BOSS), json={"user_id": str(USER_CONSULTANT)})
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "ops_admin_required"


# ---------------------------------------------------------------------------
# no-leak
# ---------------------------------------------------------------------------
async def test_overview_no_leak(client):
    await _fail_logins(client, CONSULTANT_EMAIL, 2)
    r = await client.get(OVERVIEW, headers=_hdr(USER_ADMIN_ONLY))
    assert r.status_code == 200
    text = r.text
    assert CONSULTANT_EMAIL not in text  # 无 raw email
    assert _id_hash(CONSULTANT_EMAIL) not in text  # 无完整 identifier_hash（仅前缀）
    for t in _LEAK:
        assert t not in text
    # recent_events 的 hash 前缀长度受限（不可逆，绝非 email）。
    for ev in r.json()["recent_events"]:
        if ev["identifier_hash_prefix"]:
            assert len(ev["identifier_hash_prefix"]) <= auth_security.HINT_LEN


# ---------------------------------------------------------------------------
# 手动解锁：user_id 路径
# ---------------------------------------------------------------------------
async def test_unlock_by_user_id_restores_login(client, monkeypatch):
    # 锁定 consultant（max=3 → 3 次失败后锁定）。
    await _fail_logins(client, CONSULTANT_EMAIL, 3, monkeypatch=monkeypatch, max_failed=3)
    # 锁定中：即便正确密码也统一 401。
    locked = await client.post(LOGIN, json={"email": CONSULTANT_EMAIL, "password": DEV_PASSWORD})
    assert locked.status_code == 401
    # admin 用 user_id 解锁（X-Dev-User-Id，无 cookie → 不走 CSRF）。
    u = await client.post(UNLOCK, headers=_hdr(USER_ADMIN_ONLY), json={"user_id": str(USER_CONSULTANT)})
    assert u.status_code == 200, u.text
    body = u.json()
    assert body["ok"] is True and body["unlocked"] is True
    assert body["user_id"] == str(USER_CONSULTANT)
    assert body["identifier_hash_prefix"] and body["reset_at"]
    # 解锁后正确密码可登录。
    ok = await client.post(LOGIN, json={"email": CONSULTANT_EMAIL, "password": DEV_PASSWORD})
    assert ok.status_code == 200, ok.text


async def test_unlock_unknown_user_404(client):
    r = await client.post(UNLOCK, headers=_hdr(USER_ADMIN_ONLY), json={"user_id": str(uuid.uuid4())})
    assert r.status_code == 404
    assert r.json()["detail"]["denied_reason"] == "unlock_user_not_found"


async def test_unlock_requires_exactly_one_input(client):
    r = await client.post(UNLOCK, headers=_hdr(USER_ADMIN_ONLY), json={})
    assert r.status_code == 422
    assert r.json()["detail"]["denied_reason"] == "unlock_input_invalid"


# ---------------------------------------------------------------------------
# 手动解锁：identifier_hash_prefix 路径
# ---------------------------------------------------------------------------
async def test_unlock_by_prefix_unique(client):
    await _fail_logins(client, CONSULTANT_EMAIL, 2)
    prefix = _id_hash(CONSULTANT_EMAIL)[:16]
    r = await client.post(UNLOCK, headers=_hdr(USER_ADMIN_ONLY), json={"identifier_hash_prefix": prefix})
    assert r.status_code == 200, r.text
    assert r.json()["unlocked"] is True


async def test_unlock_prefix_not_found_404(client):
    r = await client.post(UNLOCK, headers=_hdr(USER_ADMIN_ONLY),
                          json={"identifier_hash_prefix": "abcdef0123456789"})
    assert r.status_code == 404
    assert r.json()["detail"]["denied_reason"] == "unlock_identifier_not_found"


async def test_unlock_prefix_too_short_422(client):
    r = await client.post(UNLOCK, headers=_hdr(USER_ADMIN_ONLY), json={"identifier_hash_prefix": "abc"})
    assert r.status_code == 422
    assert r.json()["detail"]["denied_reason"] == "unlock_prefix_too_short"


@pytest.mark.parametrize("bad_prefix", ["________", "%%%%%%%%", "abc123zz", "ab cd ef0"])
async def test_unlock_prefix_rejects_non_hex(client, db_session, bad_prefix):
    """非 hex / SQL 通配符前缀 → 422 unlock_prefix_invalid，且不写解锁审计。"""
    # 先制造一条近期 attempt：旧实现的 `LIKE '________%'` 会误匹配它，新实现先按 hex 拒绝。
    await _fail_logins(client, CONSULTANT_EMAIL, 1)
    r = await client.post(UNLOCK, headers=_hdr(USER_ADMIN_ONLY),
                          json={"identifier_hash_prefix": bad_prefix})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["denied_reason"] == "unlock_prefix_invalid"
    ev = (await db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "auth.lockout_unlocked")
    )).scalars().all()
    assert ev == []  # 非法前缀不触发解锁


async def test_unlock_prefix_accepts_uppercase_hex(client):
    """大写 hex 前缀可 lower 后唯一匹配并解锁；响应仍返回安全小写 hash 前缀。"""
    await _fail_logins(client, CONSULTANT_EMAIL, 2)
    prefix_upper = _id_hash(CONSULTANT_EMAIL)[:16].upper()
    r = await client.post(UNLOCK, headers=_hdr(USER_ADMIN_ONLY),
                          json={"identifier_hash_prefix": prefix_upper})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["unlocked"] is True
    # 响应 hash 前缀为小写、不回显大写输入。
    assert body["identifier_hash_prefix"] == body["identifier_hash_prefix"].lower()
    assert prefix_upper not in r.text


async def test_unlock_prefix_ambiguous_409(client, db_session):
    # 构造两个不同 identifier_hash 共享一个前缀（人为同前缀，验证 409）。
    shared = "deadbeefdead"
    for suffix in ("aaaa", "bbbb"):
        db_session.add(AuthLoginAttempt(
            identifier_hash=shared + suffix + "0" * (64 - len(shared) - 4),
            identifier_hint=shared, user_id=None, ip_hash=None,
            login_method="password", result="failed", reason_code="invalid_credentials", trace_id="t",
        ))
    await db_session.commit()
    r = await client.post(UNLOCK, headers=_hdr(USER_ADMIN_ONLY),
                          json={"identifier_hash_prefix": shared})
    assert r.status_code == 409
    assert r.json()["detail"]["denied_reason"] == "unlock_identifier_ambiguous"


# ---------------------------------------------------------------------------
# 解锁不重置 IP rate limit（服务层确定性）
# ---------------------------------------------------------------------------
async def test_unlock_does_not_reset_ip_rate_limit(client, db_session):
    s = Settings(app_env="test", auth_ip_max_failed_attempts=2, auth_max_failed_attempts=100)
    idh = _id_hash("ipuser@dev.local")
    iph = auth_security.hash_login_identifier("203.0.113.50", purpose="ip")
    for _ in range(2):
        await auth_security.record_login_attempt(
            db_session, identifier_hash=idh, ip_hash=iph, user_id=None,
            login_method="password", result="failed", reason_code="invalid_credentials", trace_id="t",
        )
    await db_session.commit()
    # 确认 IP 已限流。
    g0 = await auth_security.check_login_guard(db_session, identifier_hash=idh, ip_hash=iph, settings=s)
    assert g0.result == "rate_limited"
    # admin 用前缀解锁该 identifier。
    r = await client.post(UNLOCK, headers=_hdr(USER_ADMIN_ONLY), json={"identifier_hash_prefix": idh[:16]})
    assert r.status_code == 200, r.text
    # 解锁后：identifier 已重置，但 IP 维度仍限流。
    g1 = await auth_security.check_login_guard(db_session, identifier_hash=idh, ip_hash=iph, settings=s)
    assert g1.result == "rate_limited"


# ---------------------------------------------------------------------------
# 审计安全
# ---------------------------------------------------------------------------
async def test_unlock_writes_safe_audit(client, db_session):
    await _fail_logins(client, CONSULTANT_EMAIL, 2)
    await client.post(UNLOCK, headers=_hdr(USER_ADMIN_ONLY), json={"user_id": str(USER_CONSULTANT)})
    ev = (await db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "auth.lockout_unlocked")
    )).scalars().all()
    assert ev, "解锁应写 auth.lockout_unlocked 审计"
    e = ev[0]
    assert e.actor_user_id == USER_ADMIN_ONLY
    extra = e.extra or {}
    assert extra.get("target_user_id") == str(USER_CONSULTANT)
    assert extra.get("identifier_hash_prefix") and "reset_attempt_id" in extra
    blob = str([(x.extra, x.before_snapshot, x.after_snapshot) for x in ev])
    for t in [CONSULTANT_EMAIL, _id_hash(CONSULTANT_EMAIL), "password_hash", "salt", "digest"]:
        assert t not in blob


# ---------------------------------------------------------------------------
# CSRF 覆盖解锁 POST
# ---------------------------------------------------------------------------
async def test_unlock_without_csrf_forbidden_no_audit(client, db_session):
    await client.post(LOGIN, json={"email": ADMIN_EMAIL})  # cookie 会话
    r = await client.post(UNLOCK, json={"user_id": str(USER_CONSULTANT)})  # 无 X-CSRF-Token
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "csrf_token_missing"
    ev = (await db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "auth.lockout_unlocked")
    )).scalars().all()
    assert ev == []  # CSRF 失败 → 无解锁审计


async def test_unlock_with_csrf_succeeds(client):
    await client.post(LOGIN, json={"email": ADMIN_EMAIL})  # cookie 会话
    csrf = (await client.get(CSRF)).json()["csrf_token"]
    r = await client.post(UNLOCK, headers={"X-CSRF-Token": csrf}, json={"user_id": str(USER_CONSULTANT)})
    assert r.status_code == 200, r.text
    assert r.json()["unlocked"] is True

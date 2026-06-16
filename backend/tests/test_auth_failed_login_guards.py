"""登录失败守卫与安全审计测试。

覆盖：
- known / unknown 失败都写不可逆 attempt；统一 401，不泄露账号存在性；
- 连续失败达阈值 → identifier 锁定，锁定路径不调用真实 verify_password；
- 成功登录写 success 并重置后续失败计数；
- IP 维度限流（服务层确定性测试，避免测试传输 client 不确定性）；
- prod `/health/config` 缺 AUTH_ATTEMPT_HASH_SECRET → production blocker；非 prod 不阻断；
- attempts / 审计 / 响应不含 raw email / password / hash / salt / digest / token / cookie。
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.config import Settings
from app.models.audit import AuditEvent
from app.models.auth_security import AuthLoginAttempt
from app.seed.dev_seed import DEV_PASSWORD, USER_BOSS
from app.services import auth_security

LOGIN = "/api/v1/auth/login"
CONFIG = "/health/config"
BOSS_EMAIL = "boss.c@dev.local"
UNKNOWN_EMAIL = "ghost@dev.local"


def _settings(**kw) -> Settings:
    base = dict(app_env="test", auth_attempt_hash_secret="test-secret")
    base.update(kw)
    return Settings(**base)


def _patch_settings(monkeypatch, **kw):
    s = _settings(**kw)
    monkeypatch.setattr("app.api.auth.get_settings", lambda: s)
    return s


async def _attempts(db_session, *, identifier_hash=None):
    stmt = select(AuthLoginAttempt).order_by(AuthLoginAttempt.created_at)
    if identifier_hash is not None:
        stmt = stmt.where(AuthLoginAttempt.identifier_hash == identifier_hash)
    return list((await db_session.execute(stmt)).scalars().all())


def _id_hash(email):
    return auth_security.hash_login_identifier(
        auth_security.normalize_login_identifier(email), purpose="identifier"
    )


# ---------------------------------------------------------------------------
# 1. known / unknown 失败记录
# ---------------------------------------------------------------------------
async def test_known_user_wrong_password_records_failed_attempt(client, db_session):
    r = await client.post(LOGIN, json={"email": BOSS_EMAIL, "password": "definitely-wrong"})
    assert r.status_code == 401
    assert r.json()["detail"]["denied_reason"] == "invalid_credentials"
    rows = await _attempts(db_session, identifier_hash=_id_hash(BOSS_EMAIL))
    assert len(rows) == 1
    a = rows[0]
    assert a.result == "failed"
    assert a.reason_code == "invalid_credentials"
    assert a.user_id == USER_BOSS
    # 不可逆：identifier_hash 不含 raw email。
    assert BOSS_EMAIL not in a.identifier_hash
    assert "definitely-wrong" not in r.text


async def test_unknown_email_records_attempt_user_null_no_raw_email(client, db_session):
    r = await client.post(LOGIN, json={"email": UNKNOWN_EMAIL, "password": "whatever-pass"})
    assert r.status_code == 401
    rows = await _attempts(db_session, identifier_hash=_id_hash(UNKNOWN_EMAIL))
    assert len(rows) == 1
    assert rows[0].user_id is None
    assert rows[0].result == "failed"
    # 未知 email 写系统级安全审计（actor=None），extra 只含不可逆 hash 前缀，无 raw email。
    ev = (await db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "login.failed", AuditEvent.actor_user_id.is_(None))
    )).scalars().all()
    assert ev, "未知 email 失败应写系统审计"
    blob = str([(e.extra, e.before_snapshot, e.after_snapshot) for e in ev])
    assert UNKNOWN_EMAIL not in blob
    assert UNKNOWN_EMAIL not in r.text
    assert ev[0].extra.get("identifier_hash_prefix")
    assert "identifier_hash_prefix" in ev[0].extra and "reason_code" in ev[0].extra


# ---------------------------------------------------------------------------
# 2. 锁定：达阈值后不再做真实 verify_password
# ---------------------------------------------------------------------------
async def test_lockout_after_threshold_skips_verify(client, db_session, monkeypatch):
    _patch_settings(monkeypatch, auth_max_failed_attempts=3)
    calls = []
    import app.services.passwords as passwords

    real = passwords.verify_password

    def _counting(pw, enc):
        calls.append(1)
        return real(pw, enc)

    monkeypatch.setattr(passwords, "verify_password", _counting)

    # 3 次错误密码：每次都做真实校验。
    for _ in range(3):
        r = await client.post(LOGIN, json={"email": BOSS_EMAIL, "password": "wrong-pw"})
        assert r.status_code == 401
    assert len(calls) == 3

    # 第 4 次：守卫命中 → 不调用真实 verify_password，仍统一 401。
    r4 = await client.post(LOGIN, json={"email": BOSS_EMAIL, "password": "wrong-pw"})
    assert r4.status_code == 401
    assert r4.json()["detail"]["denied_reason"] == "invalid_credentials"
    assert len(calls) == 3, "锁定路径不得再调用真实 verify_password"

    rows = await _attempts(db_session, identifier_hash=_id_hash(BOSS_EMAIL))
    assert [a.result for a in rows] == ["failed", "failed", "failed", "locked"]
    assert rows[-1].reason_code == "identifier_locked"
    # 锁定审计为系统事件（actor=None），不泄露账号存在性 / raw email。
    ev = (await db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "login.locked")
    )).scalars().all()
    assert ev and ev[0].actor_user_id is None
    assert BOSS_EMAIL not in str([e.extra for e in ev])


async def test_lockout_response_does_not_reveal_lock_state(client, monkeypatch):
    """锁定响应与错误密码响应完全一致（不区分 locked / wrong），不泄露内部阈值。"""
    _patch_settings(monkeypatch, auth_max_failed_attempts=2)
    for _ in range(2):
        await client.post(LOGIN, json={"email": BOSS_EMAIL, "password": "nope"})
    locked = await client.post(LOGIN, json={"email": BOSS_EMAIL, "password": "nope"})
    assert locked.status_code == 401
    body = locked.json()
    assert body["detail"]["denied_reason"] == "invalid_credentials"
    for token in ["locked", "lock", "锁定", "rate", "attempt", "threshold"]:
        assert token not in locked.text


# ---------------------------------------------------------------------------
# 3. 成功登录重置失败计数
# ---------------------------------------------------------------------------
async def test_success_resets_failed_count(client, db_session, monkeypatch):
    _patch_settings(monkeypatch, auth_max_failed_attempts=2)
    # wrong, success, 然后再来满额失败才锁定（证明 success 重置预算）。
    await client.post(LOGIN, json={"email": BOSS_EMAIL, "password": "wrong"})
    ok = await client.post(LOGIN, json={"email": BOSS_EMAIL, "password": DEV_PASSWORD})
    assert ok.status_code == 200
    # success 后：两次失败仍被允许（真实校验），第三次才锁定。
    r1 = await client.post(LOGIN, json={"email": BOSS_EMAIL, "password": "wrong"})
    r2 = await client.post(LOGIN, json={"email": BOSS_EMAIL, "password": "wrong"})
    r3 = await client.post(LOGIN, json={"email": BOSS_EMAIL, "password": "wrong"})
    assert r1.status_code == r2.status_code == r3.status_code == 401
    rows = await _attempts(db_session, identifier_hash=_id_hash(BOSS_EMAIL))
    results = [a.result for a in rows]
    assert results == ["failed", "success", "failed", "failed", "locked"]


# ---------------------------------------------------------------------------
# 4. IP 维度限流（服务层确定性）
# ---------------------------------------------------------------------------
async def test_ip_rate_limit_service_level(db_session, monkeypatch):
    s = _settings(auth_ip_max_failed_attempts=2, auth_max_failed_attempts=100)
    ip_hash = auth_security.hash_login_identifier("203.0.113.7", purpose="ip", settings=s)
    # 同 IP、不同 identifier 的两条失败（identifier 维度不会先锁）。
    for i in range(2):
        await auth_security.record_login_attempt(
            db_session, identifier_hash=_id_hash(f"u{i}@dev.local"), ip_hash=ip_hash,
            user_id=None, login_method="password", result="failed",
            reason_code="invalid_credentials", trace_id="t",
        )
    await db_session.commit()
    guard = await auth_security.check_login_guard(
        db_session, identifier_hash=_id_hash("fresh@dev.local"), ip_hash=ip_hash, settings=s
    )
    assert guard.blocked is True
    assert guard.result == "rate_limited"
    assert guard.reason_code == "ip_rate_limited"


async def test_identifier_lock_service_resets_after_success(db_session):
    s = _settings(auth_max_failed_attempts=2, auth_lockout_minutes=15, auth_failed_window_minutes=15)
    idh = _id_hash("svc@dev.local")
    iph = auth_security.hash_login_identifier("198.51.100.9", purpose="ip", settings=s)
    for _ in range(2):
        await auth_security.record_login_attempt(
            db_session, identifier_hash=idh, ip_hash=iph, user_id=None,
            login_method="password", result="failed", reason_code="invalid_credentials", trace_id="t",
        )
    await db_session.commit()
    assert (await auth_security.check_login_guard(db_session, identifier_hash=idh, ip_hash=iph, settings=s)).blocked
    # 成功后重置：再判定不应锁定。
    await auth_security.record_login_success(
        db_session, identifier_hash=idh, ip_hash=iph, user_id=None, login_method="password", trace_id="t"
    )
    await db_session.commit()
    assert (await auth_security.check_login_guard(db_session, identifier_hash=idh, ip_hash=iph, settings=s)).blocked is False


def test_threshold_clamps_illegal_values():
    """<1 的非法阈值被钳制为安全默认，不导致无限放行。"""
    from app.services.auth_security import _clamp

    assert _clamp(0, 5) == 5
    assert _clamp(-3, 5) == 5
    assert _clamp(None, 5) == 5
    assert _clamp(7, 5) == 7


def test_hash_is_irreversible_and_purpose_namespaced():
    s = _settings()
    h_id = auth_security.hash_login_identifier("a@b.com", purpose="identifier", settings=s)
    h_ip = auth_security.hash_login_identifier("a@b.com", purpose="ip", settings=s)
    assert "a@b.com" not in h_id
    assert len(h_id) == 64
    assert h_id != h_ip  # purpose 命名空间隔离
    # 归一化：大小写 / 空白一致。
    assert _id_hash("Boss.C@dev.local ") == _id_hash("boss.c@dev.local")


# ---------------------------------------------------------------------------
# 5. /health/config blocker
# ---------------------------------------------------------------------------
async def test_prod_missing_auth_secret_is_blocker(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.ops.get_settings",
        lambda: Settings(app_env="prod", celery_task_always_eager=False,
                         session_cookie_secure=True, auth_attempt_hash_secret=""),
    )
    monkeypatch.setattr("app.api.ops.weknora_enabled", lambda: False)
    r = await client.get(CONFIG)
    assert "AUTH_ATTEMPT_HASH_SECRET" in r.json()["production_blockers"]


async def test_prod_with_auth_secret_not_blocker(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.ops.get_settings",
        lambda: Settings(app_env="prod", celery_task_always_eager=False,
                         session_cookie_secure=True, auth_attempt_hash_secret="real-secret"),
    )
    monkeypatch.setattr("app.api.ops.weknora_enabled", lambda: False)
    r = await client.get(CONFIG)
    assert "AUTH_ATTEMPT_HASH_SECRET" not in r.json()["production_blockers"]


async def test_local_missing_secret_not_blocker(client):
    r = await client.get(CONFIG)
    assert r.json()["production_blockers"] == []  # 非 prod 不阻断


# ---------------------------------------------------------------------------
# 6. no-leak 总检
# ---------------------------------------------------------------------------
async def test_no_leak_in_attempts_audit_response(client, db_session, monkeypatch):
    _patch_settings(monkeypatch, auth_max_failed_attempts=2)
    for _ in range(3):
        r = await client.post(LOGIN, json={"email": BOSS_EMAIL, "password": "secretpw-123"})
    # attempts + 审计聚合 blob。
    attempts = await _attempts(db_session)
    audits = (await db_session.execute(select(AuditEvent))).scalars().all()
    blob = str([(a.identifier_hash, a.identifier_hint, a.ip_hash, a.result, a.reason_code) for a in attempts])
    blob += str([(e.extra, e.before_snapshot, e.after_snapshot) for e in audits])
    blob += r.text
    for token in [BOSS_EMAIL, "secretpw-123", "password_hash", "salt", "digest", "pbkdf2",
                  "kap_session", "kap_oauth_state", "token_hash"]:
        assert token not in blob, token

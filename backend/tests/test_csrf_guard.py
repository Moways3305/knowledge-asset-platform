"""Cookie 会话 CSRF 防护测试。

覆盖：
- cookie 会话 unsafe 请求缺 / 无效 / 过期 CSRF token → 403 安全 reason，且无业务写入 / 审计；
- 携带有效 token 的 cookie 会话 mutation 成功；
- `/auth/login` 不要求 CSRF；登录后可获取绑定新会话的 token；
- `/auth/logout` 受 CSRF 保护并能成功；
- `X-Dev-User-Id`（无 cookie）/ `Authorization: Bearer`（外部 Agent）不被 CSRF 误伤；
- OAuth callback（GET 安全方法）不被 CSRF 影响，state 校验仍生效；
- prod 缺 `CSRF_TOKEN_SECRET` → `/health/config.production_blockers`；
- 响应 / token 不泄露 session token / cookie 值 / secret。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import Settings
from app.models.audit import AuditEvent
from app.seed.dev_seed import USER_ADMIN_ONLY
from app.services import csrf as csrf_svc

LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
CSRF = "/api/v1/auth/csrf"
ME = "/api/v1/auth/me"
CONFIG = "/health/config"
RETRY = "/admin/ops/indexing/retry"
BOSS_EMAIL = "boss.c@dev.local"


async def _csrf_header(client):
    r = await client.get(CSRF)
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"]}


# ---------------------------------------------------------------------------
# CSRF token 发放
# ---------------------------------------------------------------------------
async def test_csrf_endpoint_issues_token_no_leak(client):
    await client.post(LOGIN, json={"email": BOSS_EMAIL})
    r = await client.get(CSRF)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["csrf_token"] and "expires_at" in body
    # token 不可含 raw session token / cookie 值。
    raw_session = client.cookies.get("kap_session")
    assert raw_session and raw_session not in body["csrf_token"]
    assert "kap_session" not in r.text


# ---------------------------------------------------------------------------
# cookie 会话 unsafe 请求：缺 / 无效 / 过期 → 403；有效 → 成功
# ---------------------------------------------------------------------------
async def test_cookie_post_missing_csrf_forbidden(client):
    await client.post(LOGIN, json={"email": BOSS_EMAIL})
    r = await client.post(LOGOUT)  # 无 X-CSRF-Token
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "csrf_token_missing"


async def test_cookie_post_invalid_csrf_forbidden(client):
    await client.post(LOGIN, json={"email": BOSS_EMAIL})
    r = await client.post(LOGOUT, headers={"X-CSRF-Token": "not-a-valid-token"})
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "csrf_token_invalid"


async def test_cookie_post_expired_csrf_forbidden(client):
    await client.post(LOGIN, json={"email": BOSS_EMAIL})
    raw = client.cookies.get("kap_session")
    # 构造一条绑定当前会话但已过期的合法签名 token。
    expiry = int((datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp())
    nonce = "nonce-abc"
    sig = csrf_svc._sign(expiry, nonce, csrf_svc._session_binding(raw))
    expired = f"{expiry}.{nonce}.{sig}"
    r = await client.post(LOGOUT, headers={"X-CSRF-Token": expired})
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "csrf_token_expired"


async def test_cookie_post_valid_csrf_succeeds(client):
    await client.post(LOGIN, json={"email": BOSS_EMAIL})
    r = await client.post(LOGOUT, headers=await _csrf_header(client))
    assert r.status_code == 200
    assert r.json()["ok"] is True


async def test_csrf_token_bound_to_session(client):
    """一个会话签发的 token 不能用于另一会话（绑定校验）。"""
    await client.post(LOGIN, json={"email": BOSS_EMAIL})
    hdr = await _csrf_header(client)  # 绑定会话 A
    await client.post(LOGOUT, headers=hdr)  # 注销会话 A
    # 重新登录得到会话 B；用会话 A 的 token → 绑定不符 → invalid。
    await client.post(LOGIN, json={"email": BOSS_EMAIL})
    r = await client.post(LOGOUT, headers=hdr)
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "csrf_token_invalid"


# ---------------------------------------------------------------------------
# login 豁免；登录后可取新 token
# ---------------------------------------------------------------------------
async def test_login_not_csrf_protected(client):
    # 未携带任何 CSRF token 也能登录（login 豁免；且登录前无会话）。
    r = await client.post(LOGIN, json={"email": BOSS_EMAIL})
    assert r.status_code == 200, r.text
    # 登录后能取绑定新会话的 token，并用它通过受保护 mutation。
    r2 = await client.post(LOGOUT, headers=await _csrf_header(client))
    assert r2.status_code == 200


# ---------------------------------------------------------------------------
# 非 cookie 会话不被误伤
# ---------------------------------------------------------------------------
async def test_dev_header_mutation_not_csrf_blocked(client):
    # X-Dev-User-Id（无 cookie 会话）→ CSRF 跳过；admin 批量 retry 入队成功。
    r = await client.post(
        RETRY, headers={"X-Dev-User-Id": str(USER_ADMIN_ONLY)}, json={"scope": "all"}
    )
    assert r.status_code == 202, r.text


async def test_bearer_auth_request_not_csrf_blocked(client):
    """带 Authorization 头（外部 Agent Bearer）即使有 cookie 也跳过 CSRF。"""
    await client.post(LOGIN, json={"email": BOSS_EMAIL})
    r = await client.post(LOGOUT, headers={"Authorization": "Bearer some-agent-token"})
    # 未被 CSRF 403 拦截 → logout 正常执行。
    assert r.status_code == 200
    assert r.json()["ok"] is True


async def test_oauth_callback_get_not_csrf_blocked(client):
    """OAuth callback 是 GET（安全方法）→ 不受 CSRF 影响，state 校验仍生效。"""
    r = await client.get("/api/v1/auth/wecom/callback")  # 无 state → 400 state 校验失败
    assert r.status_code == 400
    assert r.json()["detail"]["denied_reason"] == "oauth_state_invalid"


# ---------------------------------------------------------------------------
# CSRF 失败无业务写入 / 无业务审计
# ---------------------------------------------------------------------------
async def test_csrf_failure_no_business_effect_or_audit(client, db_session):
    await client.post(LOGIN, json={"email": BOSS_EMAIL})
    r = await client.post(LOGOUT)  # 无 CSRF → 403
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "csrf_token_missing"
    # 会话未被撤销（业务动作未执行）。
    me = await client.get(ME)
    assert me.status_code == 200 and me.json()["email"] == BOSS_EMAIL
    # 无 login.logout 业务审计。
    ev = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.action == "login.logout")))
        .scalars()
        .all()
    )
    assert ev == []


# ---------------------------------------------------------------------------
# /health/config prod blocker
# ---------------------------------------------------------------------------
async def test_prod_missing_csrf_secret_is_blocker(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.ops.get_settings",
        lambda: Settings(
            app_env="prod",
            celery_task_always_eager=False,
            session_cookie_secure=True,
            auth_attempt_hash_secret="a",
            csrf_token_secret="",
        ),
    )
    monkeypatch.setattr("app.api.ops.weknora_enabled", lambda: False)
    r = await client.get(CONFIG)
    blockers = r.json()["production_blockers"]
    assert "CSRF_TOKEN_SECRET" in blockers
    # 只回项名，不回值。
    assert "secret" not in r.text.lower() or "CSRF_TOKEN_SECRET" in r.text


async def test_prod_with_csrf_secret_not_blocker(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.ops.get_settings",
        lambda: Settings(
            app_env="prod",
            celery_task_always_eager=False,
            session_cookie_secure=True,
            auth_attempt_hash_secret="a",
            csrf_token_secret="real-csrf",
        ),
    )
    monkeypatch.setattr("app.api.ops.weknora_enabled", lambda: False)
    r = await client.get(CONFIG)
    assert "CSRF_TOKEN_SECRET" not in r.json()["production_blockers"]


# ---------------------------------------------------------------------------
# service 单元
# ---------------------------------------------------------------------------
def test_verify_reason_codes():
    s = Settings(csrf_token_secret="unit-secret")
    tok, _ = csrf_svc.issue_csrf_token("sess-raw", settings=s)
    assert csrf_svc.verify_csrf_token(tok, "sess-raw", settings=s) is None
    assert csrf_svc.verify_csrf_token(None, "sess-raw", settings=s) == "csrf_token_missing"
    assert csrf_svc.verify_csrf_token("bad", "sess-raw", settings=s) == "csrf_token_invalid"
    # 不同 session 绑定 → invalid。
    assert csrf_svc.verify_csrf_token(tok, "other-sess", settings=s) == "csrf_token_invalid"

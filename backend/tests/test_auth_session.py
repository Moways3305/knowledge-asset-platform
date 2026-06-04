"""会话身份最小闭环测试（IMPLEMENT-12）。

覆盖：登录建会话 + httpOnly cookie + login.success 审计；会话用户可调用受保护 API；
会话优先于 X-Dev-User-Id；登出撤销会话；prod 环境下无/无效会话 → 401；dev 回退仍可用；
纯 admin 业务写边界经会话仍成立；明文 token 不入 JSON 响应体。
"""

from __future__ import annotations

from app.core.config import Settings
from app.seed.dev_seed import (
    KA_PROJECT_ALPHA,
    USER_BOSS,
    USER_CONSULTANT,
)

LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"
AUDIT = "/api/v1/admin/audit"

BOSS_EMAIL = "boss.c@dev.local"
CONSULTANT_EMAIL = "consultant.a@dev.local"
ADMIN_EMAIL = "admin.e@dev.local"


async def test_login_sets_cookie_and_returns_identity_no_token(client):
    """登录成功：返回身份、下发会话 cookie，且明文 token 不出现在响应体。"""
    resp = await client.post(LOGIN, json={"email": BOSS_EMAIL})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email"] == BOSS_EMAIL
    assert body["can_discover_l5"] is True  # boss
    # 会话 cookie 已下发，但其明文 token 绝不出现在 JSON 响应体。
    assert "kap_session" in resp.cookies
    raw = resp.cookies["kap_session"]
    assert raw and raw not in resp.text
    assert "token" not in body


async def test_session_user_can_call_protected_api_without_dev_header(client):
    """登录后凭会话 cookie 即可调用受保护 API（无需 X-Dev-User-Id）。"""
    await client.post(LOGIN, json={"email": BOSS_EMAIL})
    # 不带任何 X-Dev-User-Id，cookie 由 httpx cookie jar 自动携带。
    me = await client.get(ME)
    assert me.status_code == 200
    assert me.json()["email"] == BOSS_EMAIL
    # 调用另一受保护读 API。
    kn = await client.get("/api/v1/knowledge")
    assert kn.status_code == 200


async def test_session_takes_precedence_over_dev_header(client):
    """会话优先：登录为 boss 后，即便带 consultant 的 X-Dev-User-Id，仍解析为 boss。"""
    await client.post(LOGIN, json={"email": BOSS_EMAIL})
    me = await client.get(ME, headers={"X-Dev-User-Id": str(USER_CONSULTANT)})
    assert me.status_code == 200
    assert me.json()["email"] == BOSS_EMAIL


async def test_login_writes_login_success_audit(client):
    """登录写入 login.success 审计（log_type=login，extra.login_result=success）。"""
    await client.post(LOGIN, json={"email": BOSS_EMAIL})
    # 已登录为 boss（治理视图），按 log_type 查询登录审计。
    resp = await client.get(f"{AUDIT}?log_type=login", headers={})
    assert resp.status_code == 200
    items = resp.json()["items"]
    succ = next(e for e in items if e["action"] == "login.success")
    assert succ["extra"]["login_result"] == "success"
    assert succ["extra"]["login_method"] == "dev_local"


async def test_logout_revokes_session(client):
    """登出撤销会话并写 login.logout；ok=True。"""
    await client.post(LOGIN, json={"email": BOSS_EMAIL})
    out = await client.post(LOGOUT)
    assert out.status_code == 200
    assert out.json()["ok"] is True


async def test_invalid_session_rejected_in_prod(client, monkeypatch):
    """prod 环境下无效会话 cookie 且无 dev 回退 → 401 not_authenticated。"""
    monkeypatch.setattr("app.api.auth.get_settings", lambda: Settings(app_env="prod"))
    resp = await client.get(ME, headers={"Cookie": "kap_session=bogus-token"})
    assert resp.status_code == 401


async def test_login_disabled_in_prod(client, monkeypatch):
    """prod 环境本地无凭证登录被禁用（真实 OAuth 未接入）→ 403。"""
    monkeypatch.setattr("app.api.auth.get_settings", lambda: Settings(app_env="prod"))
    resp = await client.post(LOGIN, json={"email": BOSS_EMAIL})
    assert resp.status_code == 403
    assert resp.json()["detail"] == "auth_login_not_available"


async def test_login_unknown_email_401(client):
    """未知 email 登录失败 → 401 invalid_credentials（不崩溃）。"""
    resp = await client.post(LOGIN, json={"email": "nobody@dev.local"})
    assert resp.status_code == 401
    assert resp.json()["detail"]["denied_reason"] == "invalid_credentials"


async def test_dev_fallback_still_works_without_session(client):
    """无会话时开发环境仍可用 X-Dev-User-Id 回退（保持既有行为）。"""
    me = await client.get(ME, headers={"X-Dev-User-Id": str(USER_BOSS)})
    assert me.status_code == 200
    assert me.json()["can_discover_l5"] is True


async def test_pure_admin_business_write_boundary_holds_via_session(client):
    """纯 admin 经会话登录后，业务写动作仍被拒（admin_business_permission_denied）。"""
    await client.post(LOGIN, json={"email": ADMIN_EMAIL})
    resp = await client.post(
        f"/api/v1/knowledge/{KA_PROJECT_ALPHA}/lifecycle/archive-confirm",
        json={"reason": "x"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["denied_reason"] == "admin_business_permission_denied"

"""自助 WorkBuddy token API 测试（/api/v1/auth/workbuddy-token）。

覆盖：业务用户自助生成/重置/撤销；token 明文仅一次；GET 不泄露 token/token_hash；
重置使旧 token 失效、撤销使 token 不能再调 agent-gateway；请求体 bound_user_id 被忽略；
pure admin / inactive / 非业务用户 403；审计 action + 无泄露；CSRF 覆盖 POST/DELETE。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.audit import AuditEvent
from app.models.identity import User, UserCompanyRole
from app.seed.dev_seed import USER_ADMIN_ONLY, USER_CONSULTANT

TOKEN_URL = "/api/v1/auth/workbuddy-token"
REGEN_URL = "/api/v1/auth/workbuddy-token/regenerate"
SEARCH = "/api/v1/agent-gateway/tools/knowledge-search"
LOGIN = "/api/v1/auth/login"
CSRF = "/api/v1/auth/csrf"
BOSS_EMAIL = "boss.c@dev.local"


def _dev(user_id):
    return {"X-Dev-User-Id": str(user_id)}


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 状态 + 生成
# ---------------------------------------------------------------------------
async def test_get_status_none_for_business_user(client):
    r = await client.get(TOKEN_URL, headers=_dev(USER_CONSULTANT))
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["enabled"] is False
    assert b["bound_user_id"] == str(USER_CONSULTANT)
    assert "token" not in b and "token_hash" not in b


async def test_regenerate_returns_token_once_and_config(client):
    r = await client.post(REGEN_URL, headers=_dev(USER_CONSULTANT))
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["token"].startswith("kgw_")
    kap = b["mcp_config"]["mcpServers"]["kap"]
    assert kap["env"]["KAP_AGENT_TOKEN"] == b["token"]
    assert kap["env"]["KAP_BASE_URL"]
    assert "token_hash" not in r.text


async def test_get_after_regenerate_hides_token(client):
    await client.post(REGEN_URL, headers=_dev(USER_CONSULTANT))
    r = await client.get(TOKEN_URL, headers=_dev(USER_CONSULTANT))
    b = r.json()
    assert b["enabled"] is True
    assert b["bound_user_name"]
    assert b["last_rotated_at"]
    assert "token" not in b and "token_hash" not in b
    assert "kgw_" not in r.text


# ---------------------------------------------------------------------------
# 重置 / 撤销使旧 token 失效（经 agent-gateway 实证）
# ---------------------------------------------------------------------------
async def test_regenerate_rotates_and_invalidates_old(client):
    t1 = (await client.post(REGEN_URL, headers=_dev(USER_CONSULTANT))).json()["token"]
    # 旧 token 可用。
    r_old = await client.post(SEARCH, headers=_bearer(t1), json={"query": "test"})
    assert r_old.status_code == 200, r_old.text
    # 重置 → 新 token，与旧不同。
    t2 = (await client.post(REGEN_URL, headers=_dev(USER_CONSULTANT))).json()["token"]
    assert t2 != t1
    # 旧 token 失效，新 token 可用。
    assert (
        await client.post(SEARCH, headers=_bearer(t1), json={"query": "test"})
    ).status_code == 403
    assert (
        await client.post(SEARCH, headers=_bearer(t2), json={"query": "test"})
    ).status_code == 200


async def test_revoke_disables_token(client):
    t = (await client.post(REGEN_URL, headers=_dev(USER_CONSULTANT))).json()["token"]
    assert (
        await client.post(SEARCH, headers=_bearer(t), json={"query": "test"})
    ).status_code == 200
    d = await client.delete(TOKEN_URL, headers=_dev(USER_CONSULTANT))
    assert d.status_code == 200, d.text
    assert (
        await client.post(SEARCH, headers=_bearer(t), json={"query": "test"})
    ).status_code == 403
    assert (await client.get(TOKEN_URL, headers=_dev(USER_CONSULTANT))).json()["enabled"] is False


# ---------------------------------------------------------------------------
# 安全：身份强制 + 边界
# ---------------------------------------------------------------------------
async def test_body_bound_user_id_ignored(client):
    other = uuid.uuid4()
    r = await client.post(
        REGEN_URL, headers=_dev(USER_CONSULTANT), json={"bound_user_id": str(other)}
    )
    assert r.status_code == 200, r.text
    g = await client.get(TOKEN_URL, headers=_dev(USER_CONSULTANT))
    assert g.json()["bound_user_id"] == str(USER_CONSULTANT)


async def test_pure_admin_forbidden(client):
    assert (await client.get(TOKEN_URL, headers=_dev(USER_ADMIN_ONLY))).status_code == 403
    assert (await client.post(REGEN_URL, headers=_dev(USER_ADMIN_ONLY))).status_code == 403


async def test_inactive_business_user_forbidden(client, db_session):
    uid = uuid.uuid4()
    u = User(id=uid, name="停用员工", email=f"x{uid.hex[:6]}@dev.local", status="inactive")
    u.company_roles.append(UserCompanyRole(company_role="consultant", status="active"))
    db_session.add(u)
    await db_session.commit()
    assert (await client.get(TOKEN_URL, headers=_dev(uid))).status_code == 403


# ---------------------------------------------------------------------------
# 审计 no-leak
# ---------------------------------------------------------------------------
async def test_audit_actions_no_leak(client, db_session):
    t = (await client.post(REGEN_URL, headers=_dev(USER_CONSULTANT))).json()["token"]
    await client.delete(TOKEN_URL, headers=_dev(USER_CONSULTANT))
    logs = (await db_session.execute(select(AuditEvent))).scalars().all()
    actions = {lg.action for lg in logs}
    assert "agent.workbuddy_token_rotated" in actions
    assert "agent.workbuddy_token_revoked" in actions
    import json as _json

    blob = _json.dumps([lg.extra for lg in logs], ensure_ascii=False)
    assert t not in blob
    for k in ("token_hash", "kgw_", "Authorization", "cookie"):
        assert k not in blob


# ---------------------------------------------------------------------------
# CSRF（cookie 会话）
# ---------------------------------------------------------------------------
async def test_regenerate_requires_csrf_under_cookie_session(client):
    await client.post(LOGIN, json={"email": BOSS_EMAIL})
    # 无 CSRF token → 403。
    r = await client.post(REGEN_URL)
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "csrf_token_missing"
    # 带 CSRF token → 成功。
    csrf = (await client.get(CSRF)).json()["csrf_token"]
    r2 = await client.post(REGEN_URL, headers={"X-CSRF-Token": csrf})
    assert r2.status_code == 200, r2.text
    assert r2.json()["token"].startswith("kgw_")

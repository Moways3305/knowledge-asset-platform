"""PBC-22 企微身份生命周期同步测试。

覆盖：
- OAuth 回调：有效成员建会话；失效成员 fail-closed（不建会话、停用平台用户、撤销会话、安全审计）；
  上游错误 fail-closed 不改状态；未绑定用户仍不自动建用户；
- admin 对账：停用失效绑定用户并撤销会话；dry_run 不变更；批量 clamp limit；
- 非 admin 403；
- 响应 / 审计无 access_token / app_secret / code / state / raw wecom_user_id / 通讯录档案 /
  token / cookie。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.main import app
from app.models.audit import AuditEvent
from app.models.identity import User
from app.services import session_revocation
from app.services.wecom_client import (
    WeComError,
    WeComIdentity,
    WeComMemberStatus,
    get_wecom_oauth_client,
    normalize_member_status,
)
from app.seed.dev_seed import USER_BOSS, USER_CONSULTANT, USER_ADMIN_ONLY

START = "/api/v1/auth/wecom/start"
CALLBACK = "/api/v1/auth/wecom/callback"
RECONCILE = "/admin/ops/wecom-identity/reconcile"
LOGIN = "/api/v1/auth/login"
CSRF = "/api/v1/auth/csrf"
ADMIN_EMAIL = "admin.e@dev.local"
CONSULTANT_WECOM = "ww_consultant_a"  # seed USER_CONSULTANT 绑定

_LEAK = ["access_token", "app_secret", "corpsecret", "oauth_code", "oauth_state",
         CONSULTANT_WECOM, "mobile", "avatar", "department", "token_hash", "kap_session", "errmsg"]


def _hdr(uid):
    return {"X-Dev-User-Id": str(uid)}


def _assert_no_leak(text):
    for t in _LEAK:
        assert t not in text, t


class FakeOAuth:
    def __init__(self, *, wecom_user_id=CONSULTANT_WECOM, member=None, error=None):
        self.wecom_user_id = wecom_user_id
        self._member = member
        self._error = error

    def build_authorize_url(self, *, state):
        return f"https://open.work.weixin.qq.com/wwopen/oauth2?appid=test_corp&state={state}"

    async def exchange_code(self, code):
        if not code:
            raise WeComError("wecom_missing_code", "缺少 code")
        return WeComIdentity(wecom_user_id=self.wecom_user_id)

    async def get_member_status(self, wecom_user_id):
        if self._error:
            raise self._error
        return self._member or WeComMemberStatus(wecom_user_id, True, "active", "企微成员有效")


def _install(fake):
    app.dependency_overrides[get_wecom_oauth_client] = lambda: fake


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.pop(get_wecom_oauth_client, None)


def _disabled(uid=CONSULTANT_WECOM):
    return WeComMemberStatus(uid, False, "disabled", "企微成员已禁用")


async def _oauth_login_active(client):
    """以有效企微成员走一次 OAuth 登录，给 consultant 建一条平台会话。"""
    _install(FakeOAuth())
    await client.get(START)
    state = client.cookies.get("kap_oauth_state")
    r = await client.get(CALLBACK, params={"code": "c", "state": state})
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# OAuth 回调
# ---------------------------------------------------------------------------
async def test_callback_active_member_creates_session(client):
    await _oauth_login_active(client)
    me = await client.get("/api/v1/auth/me")
    assert me.json()["user_id"] == str(USER_CONSULTANT)


async def test_callback_disabled_member_fails_closed_and_deactivates(client, db_session):
    await _oauth_login_active(client)  # 先有一条 consultant 会话
    # 再以「已禁用」成员回调 → 401 + 停用 + 撤销会话 + 审计。
    _install(FakeOAuth(member=_disabled()))
    await client.get(START)
    state = client.cookies.get("kap_oauth_state")
    r = await client.get(CALLBACK, params={"code": "c", "state": state})
    assert r.status_code == 401
    assert r.json()["detail"]["denied_reason"] == "wecom_user_inactive"
    _assert_no_leak(r.text)
    # 平台用户已停用。
    u = (await db_session.execute(select(User).where(User.id == USER_CONSULTANT))).scalar_one()
    assert u.status == "inactive"
    # 活动会话已撤销。
    assert await session_revocation.active_session_count(db_session, USER_CONSULTANT) == 0
    # 安全审计：identity.user_deactivated_by_wecom_sync（系统事件 actor=None）。
    ev = (await db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "identity.user_deactivated_by_wecom_sync")
    )).scalars().all()
    assert ev and ev[0].actor_user_id is None
    extra = ev[0].extra or {}
    assert extra.get("trigger") == "oauth_callback"
    assert extra.get("wecom_status") == "disabled"
    assert extra.get("target_user_id") == str(USER_CONSULTANT)
    _assert_no_leak(str([e.extra for e in ev]))


async def test_callback_upstream_error_fails_closed_no_status_change(client, db_session):
    _install(FakeOAuth(error=WeComError("wecom_network_error", "网络错误")))
    await client.get(START)
    state = client.cookies.get("kap_oauth_state")
    r = await client.get(CALLBACK, params={"code": "c", "state": state})
    assert r.status_code == 401
    assert r.json()["detail"]["denied_reason"] == "wecom_status_check_failed"
    # 平台状态未变（上游瞬时故障不误停用）。
    u = (await db_session.execute(select(User).where(User.id == USER_CONSULTANT))).scalar_one()
    assert u.status == "active"
    # login.failed 审计含安全 reason_code，不泄露。
    ev = (await db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "login.failed")
    )).scalars().all()
    assert any((e.extra or {}).get("reason_code") == "wecom_status_check_failed" for e in ev)
    _assert_no_leak(r.text)


async def test_callback_unprovisioned_still_no_auto_create(client):
    _install(FakeOAuth(wecom_user_id="ww_unknown_nobody"))
    await client.get(START)
    state = client.cookies.get("kap_oauth_state")
    r = await client.get(CALLBACK, params={"code": "c", "state": state})
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "user_not_provisioned"


# ---------------------------------------------------------------------------
# admin 对账
# ---------------------------------------------------------------------------
async def test_reconcile_single_deactivates_invalid(client, db_session):
    await _oauth_login_active(client)
    client.cookies.clear()  # 后续以 admin dev 头操作（无 cookie → 不走 CSRF）
    _install(FakeOAuth(member=_disabled()))
    r = await client.post(RECONCILE, headers=_hdr(USER_ADMIN_ONLY),
                          json={"user_id": str(USER_CONSULTANT)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["checked"] == 1 and body["deactivated"] == 1 and body["dry_run"] is False
    item = body["items"][0]
    assert item["wecom_status"] == "disabled" and item["new_status"] == "inactive"
    assert item["sessions_revoked"] >= 1
    u = (await db_session.execute(select(User).where(User.id == USER_CONSULTANT))).scalar_one()
    assert u.status == "inactive"
    assert await session_revocation.active_session_count(db_session, USER_CONSULTANT) == 0
    _assert_no_leak(r.text)


async def test_reconcile_dry_run_no_mutation(client, db_session):
    await _oauth_login_active(client)
    client.cookies.clear()
    _install(FakeOAuth(member=_disabled()))
    r = await client.post(RECONCILE, headers=_hdr(USER_ADMIN_ONLY),
                          json={"user_id": str(USER_CONSULTANT), "dry_run": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    # 预演：item 显示「将停用」但不实际变更。
    assert body["items"][0]["new_status"] == "inactive"
    u = (await db_session.execute(select(User).where(User.id == USER_CONSULTANT))).scalar_one()
    assert u.status == "active"  # 未变更
    assert await session_revocation.active_session_count(db_session, USER_CONSULTANT) >= 1  # 会话保留
    # dry_run 不写停用审计。
    ev = (await db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "identity.user_deactivated_by_wecom_sync")
    )).scalars().all()
    assert ev == []


async def test_reconcile_batch_clamps_limit(client):
    _install(FakeOAuth())  # 默认有效成员
    r = await client.post(RECONCILE, headers=_hdr(USER_ADMIN_ONLY), json={"limit": 9999})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["checked"] <= 200  # clamp 到安全上限
    assert isinstance(body["items"], list)


async def test_reconcile_user_not_bound_422(client):
    _install(FakeOAuth())
    # USER_BOSS 未绑定企微（seed 只有 consultant 绑定）。
    r = await client.post(RECONCILE, headers=_hdr(USER_ADMIN_ONLY), json={"user_id": str(USER_BOSS)})
    assert r.status_code == 422
    assert r.json()["detail"]["denied_reason"] == "user_not_wecom_bound"


async def test_reconcile_unknown_user_404(client):
    _install(FakeOAuth())
    r = await client.post(RECONCILE, headers=_hdr(USER_ADMIN_ONLY), json={"user_id": str(uuid.uuid4())})
    assert r.status_code == 404


async def test_reconcile_forbidden_non_admin(client):
    _install(FakeOAuth())
    r = await client.post(RECONCILE, headers=_hdr(USER_BOSS), json={})
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "ops_admin_required"


async def test_reconcile_upstream_error_counts_failed_no_status_change(client, db_session):
    _install(FakeOAuth(error=WeComError("wecom_network_error", "网络错误")))
    r = await client.post(RECONCILE, headers=_hdr(USER_ADMIN_ONLY),
                          json={"user_id": str(USER_CONSULTANT)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["failed"] == 1 and body["deactivated"] == 0
    assert body["items"][0]["error_code"] == "wecom_network_error"
    u = (await db_session.execute(select(User).where(User.id == USER_CONSULTANT))).scalar_one()
    assert u.status == "active"
    _assert_no_leak(r.text)


# ---------------------------------------------------------------------------
# normalize_member_status 归一矩阵（PBC-22 residual）
# ---------------------------------------------------------------------------
def test_normalize_member_status_matrix():
    cases = [
        ({"errcode": 0, "status": 1}, "active", True),
        ({"errcode": 0, "status": 2}, "disabled", False),
        ({"errcode": 0, "status": 4}, "not_activated", False),
        ({"errcode": 0, "status": 5}, "deleted", False),
        ({"errcode": 60111}, "deleted", False),
        ({"errcode": 60121}, "deleted", False),
        ({"errcode": 46004}, "deleted", False),
        ({"errcode": 40013}, "unknown", False),  # 未知非零 errcode
        ({"errcode": 0, "status": 9}, "unknown", False),  # 未知 status
        ({"errcode": 0}, "unknown", False),  # 缺 status（默认 0）→ unknown
    ]
    for payload, code, active in cases:
        m = normalize_member_status("ww_x", payload)
        assert m.status_code == code, payload
        assert m.active is active, payload
        assert m.wecom_user_id == "ww_x"


def test_normalize_member_status_ignores_raw_profile_fields():
    """上游档案字段（name/mobile/email/department/avatar/errmsg）不进入归一结果。"""
    payload = {
        "errcode": 0, "status": 1,
        "name": "张三", "mobile": "13800000000", "email": "z@corp.com",
        "department": [1, 2, 3], "avatar": "https://wework/avatar.png",
        "errmsg": "ok-raw-upstream-errmsg",
    }
    m = normalize_member_status("ww_x", payload)
    assert m.status_code == "active" and m.active is True
    # 归一结果只含安全 code + 安全中文文案；绝不含任何上游档案 / errmsg 原文。
    blob = f"{m.wecom_user_id}|{m.status_code}|{m.status_message}|{m.active}"
    for raw in ["张三", "13800000000", "z@corp.com", "avatar", "ok-raw-upstream-errmsg", "department"]:
        assert raw not in blob, raw
    assert m.status_message == "企微成员有效"  # 安全文案，非上游 errmsg


# ---------------------------------------------------------------------------
# OAuth 回调：非 disabled 的失效状态 end-to-end（not_activated / deleted）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("code,msg", [
    ("not_activated", "企微成员未激活"),
    ("deleted", "企微成员已退出企业"),
])
async def test_callback_invalid_state_deactivates(client, db_session, code, msg):
    await _oauth_login_active(client)  # 先有一条 consultant 会话
    _install(FakeOAuth(member=WeComMemberStatus(CONSULTANT_WECOM, False, code, msg)))
    await client.get(START)
    state = client.cookies.get("kap_oauth_state")
    r = await client.get(CALLBACK, params={"code": "c", "state": state})
    assert r.status_code == 401
    assert r.json()["detail"]["denied_reason"] == "wecom_user_inactive"
    u = (await db_session.execute(select(User).where(User.id == USER_CONSULTANT))).scalar_one()
    assert u.status == "inactive"
    assert await session_revocation.active_session_count(db_session, USER_CONSULTANT) == 0
    ev = (await db_session.execute(
        select(AuditEvent).where(AuditEvent.action == "identity.user_deactivated_by_wecom_sync")
    )).scalars().all()
    assert ev and (ev[0].extra or {}).get("wecom_status") == code
    assert (ev[0].extra or {}).get("trigger") == "oauth_callback"
    _assert_no_leak(r.text)
    _assert_no_leak(str([e.extra for e in ev]))


# ---------------------------------------------------------------------------
# reconcile cookie-auth CSRF（PBC-19 中间件覆盖）
# ---------------------------------------------------------------------------
async def test_reconcile_cookie_auth_without_csrf_forbidden_no_mutation(client, db_session):
    _install(FakeOAuth(member=_disabled()))  # 若放行将停用 consultant
    await client.post(LOGIN, json={"email": ADMIN_EMAIL})  # admin cookie 会话
    r = await client.post(RECONCILE, json={"user_id": str(USER_CONSULTANT)})  # 无 X-CSRF-Token
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "csrf_token_missing"
    # 业务未执行：状态未变、无对账 / 停用审计。
    u = (await db_session.execute(select(User).where(User.id == USER_CONSULTANT))).scalar_one()
    assert u.status == "active"
    ev = (await db_session.execute(
        select(AuditEvent).where(AuditEvent.action.in_(
            ["identity.wecom_user_synced", "identity.user_deactivated_by_wecom_sync"]
        ))
    )).scalars().all()
    assert ev == []


async def test_reconcile_cookie_auth_with_csrf_succeeds(client):
    _install(FakeOAuth())  # 有效成员
    await client.post(LOGIN, json={"email": ADMIN_EMAIL})
    csrf = (await client.get(CSRF)).json()["csrf_token"]
    r = await client.post(RECONCILE, headers={"X-CSRF-Token": csrf}, json={})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

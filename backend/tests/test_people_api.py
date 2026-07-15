"""人员 / 公司角色 / 项目成员关系治理 API 测试。

覆盖：读权限（boss/director vs admin/consultant 403）、公司角色 upsert（业务角色层级与技术
admin 浏览器禁配）、项目成员 upsert / patch（归属校验）、inactive 成员不进
权限上下文、写审计安全无泄露、admin 业务边界不被破坏。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.audit import AuditEvent
from app.seed.dev_seed import (
    PROJECT_ALPHA,
    PROJECT_BETA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
    USER_PROJECT_MANAGER,
)
from app.services.identity import load_user_with_roles
from app.services.permission import build_caller_context

PEOPLE = "/api/v1/admin/people"

_LEAK_TOKENS = [
    "token_hash",
    "kap_session",
    "device_info",
    "ip_address",
    "oauth_state",
    "auth_code",
    "app_secret",
    "storage_ref",
    "source_file_ref",
    "api_key",
    "wecom_user_id",
]


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


def _assert_no_leak(text: str):
    for t in _LEAK_TOKENS:
        assert t not in text, f"响应不应泄露 {t}"


# ---------------- 读权限 ----------------
async def test_admin_cannot_list_people(client):
    r = await client.get(PEOPLE, headers=_hdr(USER_ADMIN_ONLY))
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "admin_business_permission_denied"


async def test_admin_is_rejected_by_every_people_route_without_enumeration(client):
    unknown_user = uuid.uuid4()
    unknown_membership = uuid.uuid4()
    calls = (
        ("GET", f"{PEOPLE}/{unknown_user}", None),
        ("GET", f"{PEOPLE}/{unknown_user}/project-memberships", None),
        (
            "POST",
            f"{PEOPLE}/{unknown_user}/company-roles",
            {"company_role": "consultant", "status": "active"},
        ),
        (
            "POST",
            f"{PEOPLE}/{unknown_user}/project-memberships",
            {"project_id": str(PROJECT_ALPHA), "project_role": "consultant", "status": "active"},
        ),
        (
            "PATCH",
            f"{PEOPLE}/{unknown_user}/project-memberships/{unknown_membership}",
            {"status": "inactive"},
        ),
        ("POST", f"{PEOPLE}/{unknown_user}/password", {"password": "safe-pass-123"}),
        ("POST", f"{PEOPLE}/{unknown_user}/status", {"status": "inactive"}),
    )
    for method, url, payload in calls:
        response = await client.request(method, url, headers=_hdr(USER_ADMIN_ONLY), json=payload)
        assert response.status_code == 403, (method, url, response.text)
        assert response.json()["detail"]["denied_reason"] == "admin_business_permission_denied"


async def test_boss_and_director_can_list(client):
    for uid in (USER_BOSS, USER_DIRECTOR):
        r = await client.get(PEOPLE, headers=_hdr(uid))
        assert r.status_code == 200


async def test_consultant_cannot_list(client):
    r = await client.get(PEOPLE, headers=_hdr(USER_CONSULTANT))
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "people_admin_forbidden"


async def test_filters_role_and_q(client):
    # role=boss 只返回有 active boss 角色的用户。
    r = await client.get(f"{PEOPLE}?role=boss", headers=_hdr(USER_BOSS))
    assert r.status_code == 200
    ids = {i["user_id"] for i in r.json()["items"]}
    assert str(USER_BOSS) in ids and str(USER_CONSULTANT) not in ids
    # q 模糊搜索（邮箱）。
    r2 = await client.get(f"{PEOPLE}?q=director.d", headers=_hdr(USER_BOSS))
    assert r2.status_code == 200
    assert any(i["user_id"] == str(USER_DIRECTOR) for i in r2.json()["items"])


async def test_get_person_detail(client):
    r = await client.get(f"{PEOPLE}/{USER_PROJECT_MANAGER}", headers=_hdr(USER_BOSS))
    assert r.status_code == 200
    body = r.json()
    assert body["user_id"] == str(USER_PROJECT_MANAGER)
    # 有 ALPHA project_manager active 成员关系。
    roles = {(m["project_id"], m["project_role"], m["status"]) for m in body["project_memberships"]}
    assert (str(PROJECT_ALPHA), "project_manager", "active") in roles


# ---------------- 公司角色管理 ----------------
async def test_boss_can_set_business_role_but_not_admin(client):
    # boss 设置 consultant 为 consulting_director（业务角色）→ 200。
    r = await client.post(
        f"{PEOPLE}/{USER_PROJECT_MANAGER}/company-roles",
        headers=_hdr(USER_BOSS),
        json={"company_role": "consulting_director", "status": "active"},
    )
    assert r.status_code == 200, r.text
    roles = {(c["company_role"], c["status"]) for c in r.json()["company_roles"]}
    assert ("consulting_director", "active") in roles
    # boss 不能分配 admin。
    r2 = await client.post(
        f"{PEOPLE}/{USER_PROJECT_MANAGER}/company-roles",
        headers=_hdr(USER_BOSS),
        json={"company_role": "admin", "status": "active"},
    )
    assert r2.status_code == 403
    assert r2.json()["detail"]["denied_reason"] == "admin_role_browser_management_forbidden"


async def test_consultant_cannot_manage_roles(client):
    r = await client.post(
        f"{PEOPLE}/{USER_PROJECT_MANAGER}/company-roles",
        headers=_hdr(USER_CONSULTANT),
        json={"company_role": "consultant", "status": "inactive"},
    )
    assert r.status_code == 403


async def test_company_role_upsert_no_duplicate(client):
    # USER_CONSULTANT 已有 active consultant 角色；重复设置 inactive 只更新、不新增行。
    r = await client.post(
        f"{PEOPLE}/{USER_CONSULTANT}/company-roles",
        headers=_hdr(USER_BOSS),
        json={"company_role": "consultant", "status": "inactive"},
    )
    assert r.status_code == 200
    consultant_rows = [c for c in r.json()["company_roles"] if c["company_role"] == "consultant"]
    assert len(consultant_rows) == 1 and consultant_rows[0]["status"] == "inactive"


async def test_admin_role_has_no_browser_management_path(client):
    for actor in (USER_ADMIN_ONLY, USER_BOSS, USER_DIRECTOR):
        r = await client.post(
            f"{PEOPLE}/{USER_BOSS}/company-roles",
            headers=_hdr(actor),
            json={"company_role": "admin", "status": "active"},
        )
        assert r.status_code == 403
        assert r.json()["detail"]["denied_reason"] == "admin_role_browser_management_forbidden"


async def test_company_role_authorization_matrix(client):
    # 咨询总监可管理咨询总监及顾问，但不可管理总经理。
    allowed = await client.post(
        f"{PEOPLE}/{USER_PROJECT_MANAGER}/company-roles",
        headers=_hdr(USER_DIRECTOR),
        json={"company_role": "consultant", "status": "inactive"},
    )
    assert allowed.status_code == 200, allowed.text
    director = await client.post(
        f"{PEOPLE}/{USER_PROJECT_MANAGER}/company-roles",
        headers=_hdr(USER_DIRECTOR),
        json={"company_role": "consulting_director", "status": "active"},
    )
    assert director.status_code == 200
    for role in ("boss",):
        denied = await client.post(
            f"{PEOPLE}/{USER_PROJECT_MANAGER}/company-roles",
            headers=_hdr(USER_DIRECTOR),
            json={"company_role": role, "status": "active"},
        )
        assert denied.status_code == 403
        assert denied.json()["detail"]["denied_reason"] == "company_role_management_forbidden"

    # admin 对全部公司角色写入均拒绝。
    for role in ("boss", "consulting_director", "consultant", "admin"):
        denied = await client.post(
            f"{PEOPLE}/{USER_PROJECT_MANAGER}/company-roles",
            headers=_hdr(USER_ADMIN_ONLY),
            json={"company_role": role, "status": "active"},
        )
        assert denied.status_code == 403
        expected = (
            "admin_role_browser_management_forbidden"
            if role == "admin"
            else "admin_business_permission_denied"
        )
        assert denied.json()["detail"]["denied_reason"] == expected


async def test_last_active_boss_protected_and_handoff(client):
    blocked = await client.post(
        f"{PEOPLE}/{USER_BOSS}/company-roles",
        headers=_hdr(USER_BOSS),
        json={"company_role": "boss", "status": "inactive"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["denied_reason"] == "last_active_boss_protected"

    grant = await client.post(
        f"{PEOPLE}/{USER_PROJECT_MANAGER}/company-roles",
        headers=_hdr(USER_BOSS),
        json={"company_role": "boss", "status": "active"},
    )
    assert grant.status_code == 200
    handoff = await client.post(
        f"{PEOPLE}/{USER_BOSS}/company-roles",
        headers=_hdr(USER_BOSS),
        json={"company_role": "boss", "status": "inactive"},
    )
    assert handoff.status_code == 200


async def test_admin_cannot_manage_user_status(client):
    response = await client.post(
        f"{PEOPLE}/{USER_BOSS}/status",
        headers=_hdr(USER_ADMIN_ONLY),
        json={"status": "inactive"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["denied_reason"] == "admin_business_permission_denied"


async def test_governance_can_manage_account_but_director_cannot_manage_boss(client):
    allowed = await client.post(
        f"{PEOPLE}/{USER_CONSULTANT}/status",
        headers=_hdr(USER_DIRECTOR),
        json={"status": "inactive"},
    )
    assert allowed.status_code == 200
    denied = await client.post(
        f"{PEOPLE}/{USER_BOSS}/status",
        headers=_hdr(USER_DIRECTOR),
        json={"status": "inactive"},
    )
    assert denied.status_code == 403
    assert (
        denied.json()["detail"]["denied_reason"]
        == "consulting_director_cannot_manage_general_manager"
    )


# ---------------- 项目成员关系管理 ----------------
async def test_membership_upsert_no_duplicate(client):
    # 项目经理任命 coach，治理角色再任命为 project_manager，更新同一行。
    r1 = await client.post(
        f"{PEOPLE}/{USER_DIRECTOR}/project-memberships",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={"project_id": str(PROJECT_ALPHA), "project_role": "coach", "status": "active"},
    )
    assert r1.status_code == 200, r1.text
    mid = r1.json()["membership_id"]
    r2 = await client.post(
        f"{PEOPLE}/{USER_DIRECTOR}/project-memberships",
        headers=_hdr(USER_BOSS),
        json={
            "project_id": str(PROJECT_ALPHA),
            "project_role": "project_manager",
            "status": "active",
        },
    )
    assert r2.status_code == 200
    assert r2.json()["membership_id"] == mid  # 同一行，未重复创建
    assert r2.json()["project_role"] == "project_manager"


async def test_membership_create_unknown_project_404(client):
    r = await client.post(
        f"{PEOPLE}/{USER_BOSS}/project-memberships",
        headers=_hdr(USER_BOSS),
        json={"project_id": str(uuid.uuid4()), "project_role": "consultant", "status": "active"},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["denied_reason"] == "project_not_found"


async def test_patch_membership_wrong_user_404(client):
    # 取 USER_PROJECT_MANAGER 的 ALPHA membership_id。
    lst = await client.get(
        f"{PEOPLE}/{USER_PROJECT_MANAGER}/project-memberships", headers=_hdr(USER_BOSS)
    )
    mid = next(m["membership_id"] for m in lst.json() if m["project_id"] == str(PROJECT_ALPHA))
    # 在 USER_BOSS 名下 PATCH 别人的 membership_id → 404，不泄露他人关系。
    r = await client.patch(
        f"{PEOPLE}/{USER_BOSS}/project-memberships/{mid}",
        headers=_hdr(USER_BOSS),
        json={"status": "inactive"},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["denied_reason"] == "membership_not_found"


async def test_patch_membership_deactivate_then_not_in_caller_context(client, db_session):
    # 项目经理给 USER_BOSS 创建 ALPHA consultant，再由项目经理停用。
    create = await client.post(
        f"{PEOPLE}/{USER_BOSS}/project-memberships",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={"project_id": str(PROJECT_ALPHA), "project_role": "consultant", "status": "active"},
    )
    mid = create.json()["membership_id"]
    user = await load_user_with_roles(db_session, user_id=USER_BOSS)
    assert PROJECT_ALPHA in build_caller_context(user).active_project_ids
    # PATCH inactive → 重新加载后不再出现在 active_project_ids。
    patch = await client.patch(
        f"{PEOPLE}/{USER_BOSS}/project-memberships/{mid}",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={"status": "inactive"},
    )
    assert patch.status_code == 200
    db_session.expire_all()  # 丢弃本 session 的身份映射缓存，强制从已提交数据重读
    user2 = await load_user_with_roles(db_session, user_id=USER_BOSS)
    assert PROJECT_ALPHA not in build_caller_context(user2).active_project_ids


async def test_admin_cannot_manage_project_memberships(client):
    response = await client.post(
        f"{PEOPLE}/{USER_BOSS}/project-memberships",
        headers=_hdr(USER_ADMIN_ONLY),
        json={"project_id": str(PROJECT_ALPHA), "project_role": "consultant", "status": "active"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["denied_reason"] == "admin_business_permission_denied"


async def test_consultant_seed_inactive_beta_not_in_context(client, db_session):
    # 既有 seed：USER_CONSULTANT 在 BETA 为 inactive 成员 → 不进 active_project_ids。
    user = await load_user_with_roles(db_session, user_id=USER_CONSULTANT)
    ctx = build_caller_context(user)
    assert PROJECT_ALPHA in ctx.active_project_ids
    assert PROJECT_BETA not in ctx.active_project_ids


# ---------------- 审计安全 ----------------
async def test_write_audits_with_safe_extra(client, db_session):
    await client.post(
        f"{PEOPLE}/{USER_PROJECT_MANAGER}/company-roles",
        headers={**_hdr(USER_BOSS), "X-Trace-Id": "trc-people-role"},
        json={"company_role": "consultant", "status": "inactive"},
    )
    rows = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "config.people_company_role_updated")
            )
        )
        .scalars()
        .all()
    )
    assert rows, "应写入 config.people_company_role_updated 审计事件"
    ev = rows[-1]
    extra = ev.extra or {}
    assert "target_user_id" not in extra
    assert str(USER_PROJECT_MANAGER) not in str(extra)
    assert extra.get("company_role") == "consultant"
    assert "new_status" in extra
    blob = str(extra)
    for t in _LEAK_TOKENS:
        assert t not in blob


async def test_denied_business_role_write_is_audited_without_target_identity(client, db_session):
    response = await client.post(
        f"{PEOPLE}/{USER_PROJECT_MANAGER}/company-roles",
        headers={**_hdr(USER_ADMIN_ONLY), "X-Trace-Id": "trc-role-denied"},
        json={"company_role": "consultant", "status": "active"},
    )
    assert response.status_code == 403
    event = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.trace_id == "trc-role-denied",
                AuditEvent.action == "config.people_company_role_updated",
            )
        )
    ).scalar_one()
    assert event.target_id is None
    assert (event.extra or {}).get("denied_reason") == "admin_business_permission_denied"
    assert str(USER_PROJECT_MANAGER) not in str(event.extra)


# ---------------- admin 业务边界 ----------------
async def test_admin_not_business_user(client, db_session):
    # 纯 admin 不是业务用户、无项目原文权限（active_project_ids 空、is_business_user False）。
    user = await load_user_with_roles(db_session, user_id=USER_ADMIN_ONLY)
    ctx = build_caller_context(user)
    assert ctx.is_business_user is False
    assert ctx.active_project_ids == set()

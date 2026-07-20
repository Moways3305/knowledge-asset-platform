"""项目设置 / 项目成员管理 API 测试。

覆盖：读权限（成员 / 非成员 / admin / 治理角色）、写权限（仅 pm，admin / 治理 / 普通成员拒绝）、
wecom_group_id 安全展示与审计脱敏、成员角色/状态修改与 active
成员上下文、最后管理角色保护、未知 project/member 404、写审计安全无泄露。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.audit import AuditEvent
from app.seed.dev_seed import (
    KA_PROJECT_ALPHA,
    KA_PROJECT_BETA_L3,
    PROJECT_ALPHA,
    PROJECT_BETA,
    REVIEW_SEED,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
    USER_PROJECT_MANAGER,
)
from app.services.identity import load_user_with_roles
from app.services.permission import build_caller_context


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


_LEAK_TOKENS = [
    "wecom_user_id",
    "access_token",
    "oauth_state",
    "auth_code",
    "download_url",
    "storage_ref",
    "source_file_ref",
    "weknora",
    "token_hash",
    "app_secret",
    "ww_consultant",
]


def _assert_no_leak(text: str):
    low = text.lower()
    for t in _LEAK_TOKENS:
        assert t.lower() not in low, f"不应泄露 {t}"


def _settings(pid):
    return f"/api/v1/projects/{pid}/settings"


def _members(pid):
    return f"/api/v1/projects/{pid}/members"


# ---------------- 读权限 ----------------
async def test_member_can_read_settings(client):
    r = await client.get(_settings(PROJECT_ALPHA), headers=_hdr(USER_CONSULTANT))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["project_id"] == str(PROJECT_ALPHA)
    assert body["can_write"] is False  # consultant 成员只读
    _assert_no_leak(r.text)


async def test_non_member_consultant_forbidden(client):
    # USER_CONSULTANT 在 Beta 为 inactive 成员 → 非 active 成员 → 403。
    r = await client.get(_settings(PROJECT_BETA), headers=_hdr(USER_CONSULTANT))
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "project_membership_required"


async def test_admin_cannot_read_or_write_business_project(client):
    r = await client.get(_settings(PROJECT_ALPHA), headers=_hdr(USER_ADMIN_ONLY))
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "project_membership_required"
    w = await client.patch(
        _settings(PROJECT_ALPHA),
        headers=_hdr(USER_ADMIN_ONLY),
        json={"force_review_on_ingest": True},
    )
    assert w.status_code == 403
    assert w.json()["detail"]["denied_reason"] == "admin_business_permission_denied"


async def test_governance_can_read(client):
    for uid in (USER_BOSS, USER_DIRECTOR):
        r = await client.get(_settings(PROJECT_ALPHA), headers=_hdr(uid))
        assert r.status_code == 200
        assert r.json()["can_write"] is False


# ---------------- 写权限 ----------------
async def test_project_manager_can_update(client):
    r = await client.patch(
        _settings(PROJECT_ALPHA),
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "lifecycle_route_key": "route_B",
            "lifecycle_phase_key": "行动辅导",
            "force_review_on_ingest": True,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["lifecycle_route_key"] == "route_B"
    assert body["force_review_on_ingest"] is True
    assert body["can_write"] is True


async def test_consultant_member_cannot_update(client):
    r = await client.patch(
        _settings(PROJECT_ALPHA),
        headers=_hdr(USER_CONSULTANT),
        json={"force_review_on_ingest": True},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "project_settings_write_forbidden"


async def test_governance_cannot_update_project_settings(client):
    for uid, phase in ((USER_BOSS, "阶段评估"), (USER_DIRECTOR, "年度复盘")):
        r = await client.patch(
            _settings(PROJECT_ALPHA),
            headers=_hdr(uid),
            json={"lifecycle_phase_key": phase},
        )
        assert r.status_code == 403
        assert r.json()["detail"]["denied_reason"] == "project_membership_required"


# ---------------- wecom_group_id 安全 + 审计 ----------------
async def test_wecom_group_safe_display_and_audit(client, db_session):
    secret_group = "wg-secret-987654"
    r = await client.patch(
        _settings(PROJECT_ALPHA),
        headers={**_hdr(USER_PROJECT_MANAGER), "X-Trace-Id": "trc-project-settings-wecom"},
        json={"wecom_group_id": secret_group},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # 响应只回 bound + 脱敏 label，绝不回全文。
    assert body["wecom_group_bound"] is True
    assert body["wecom_group_label"] == "···7654"
    assert secret_group not in r.text
    assert "wecom_group_id" not in body

    # 审计：只记 changed_fields + bound，绝不含 wecom_group_id 全文。
    rows = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "project.settings_updated")
            )
        )
        .scalars()
        .all()
    )
    assert rows
    ev = rows[-1]
    assert ev.target_type == "project" and ev.target_id == PROJECT_ALPHA
    blob = str(ev.extra) + str(ev.before_snapshot) + str(ev.after_snapshot)
    assert secret_group not in blob
    assert "wecom_group_id" in (ev.extra or {}).get("changed_fields", [])
    assert (ev.after_snapshot or {}).get("wecom_group_bound") is True


# ---------------- 成员读 / 改 ----------------
async def test_list_members_safe_fields(client):
    r = await client.get(_members(PROJECT_ALPHA), headers=_hdr(USER_PROJECT_MANAGER))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] >= 2 and body["can_manage"] is True
    m = body["items"][0]
    for k in (
        "member_id",
        "user_id",
        "name",
        "email",
        "company_roles",
        "project_role",
        "status",
        "wecom_bound",
        "source",
    ):
        assert k in m
    _assert_no_leak(r.text)  # 不含 wecom_user_id 明文（ww_consultant...）


async def test_patch_member_then_not_in_active_context(client, db_session):
    lst = await client.get(_members(PROJECT_ALPHA), headers=_hdr(USER_PROJECT_MANAGER))
    cons = next(m for m in lst.json()["items"] if m["user_id"] == str(USER_CONSULTANT))
    r = await client.patch(
        f"{_members(PROJECT_ALPHA)}/{cons['member_id']}",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={"status": "inactive"},
    )
    assert r.status_code == 200, r.text
    db_session.expire_all()
    user = await load_user_with_roles(db_session, user_id=USER_CONSULTANT)
    assert PROJECT_ALPHA not in build_caller_context(user).active_project_ids


async def test_last_management_role_protected(client):
    # Alpha 仅一个 active 管理角色（USER_PROJECT_MANAGER）；停用它 → 409。
    lst = await client.get(_members(PROJECT_ALPHA), headers=_hdr(USER_BOSS))
    pm = next(m for m in lst.json()["items"] if m["user_id"] == str(USER_PROJECT_MANAGER))
    r = await client.patch(
        f"{_members(PROJECT_ALPHA)}/{pm['member_id']}",
        headers=_hdr(USER_BOSS),
        json={"status": "inactive"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["denied_reason"] == "last_project_manager_protected"
    # 治理角色只能任命/撤销项目经理，不把项目经理改成普通项目角色。
    r2 = await client.patch(
        f"{_members(PROJECT_ALPHA)}/{pm['member_id']}",
        headers=_hdr(USER_BOSS),
        json={"project_role": "consultant"},
    )
    assert r2.status_code == 403
    assert r2.json()["detail"]["denied_reason"] == "project_member_management_forbidden"


async def test_member_patch_writes_audit(client, db_session):
    # 项目经理独立调整本项目顾问状态，并写安全审计。
    lst = await client.get(_members(PROJECT_ALPHA), headers=_hdr(USER_PROJECT_MANAGER))
    cons = next(m for m in lst.json()["items"] if m["user_id"] == str(USER_CONSULTANT))
    r = await client.patch(
        f"{_members(PROJECT_ALPHA)}/{cons['member_id']}",
        headers={**_hdr(USER_PROJECT_MANAGER), "X-Trace-Id": "trc-project-settings-member"},
        json={"status": "inactive"},
    )
    assert r.status_code == 200, r.text
    rows = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "project.member_updated")
            )
        )
        .scalars()
        .all()
    )
    assert rows
    ev = rows[-1]
    assert ev.target_type == "project_member"
    assert (ev.extra or {}).get("target_user_id") == str(USER_CONSULTANT)
    assert (ev.after_snapshot or {}).get("status") == "inactive"


async def test_pm_can_appoint_ordinary_active_user_as_coach_without_expanding_permissions(client):
    members = await client.get(_members(PROJECT_ALPHA), headers=_hdr(USER_PROJECT_MANAGER))
    consultant = next(
        item for item in members.json()["items"] if item["user_id"] == str(USER_CONSULTANT)
    )
    appointed = await client.patch(
        f"{_members(PROJECT_ALPHA)}/{consultant['member_id']}",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={"project_role": "coach", "status": "active"},
    )
    assert appointed.status_code == 200, appointed.text
    assert appointed.json()["project_role"] == "coach"

    own_project = await client.get(
        f"/api/v1/knowledge/{KA_PROJECT_ALPHA}", headers=_hdr(USER_CONSULTANT)
    )
    assert own_project.status_code == 200
    approval = await client.post(
        f"/api/v1/reviews/{REVIEW_SEED}/approve", headers=_hdr(USER_CONSULTANT)
    )
    assert approval.status_code == 403
    other_project = await client.get(
        f"/api/v1/knowledge/{KA_PROJECT_BETA_L3}", headers=_hdr(USER_CONSULTANT)
    )
    assert other_project.status_code == 404


async def test_governance_appoints_project_manager_not_coach(client):
    response = await client.post(
        _members(PROJECT_ALPHA),
        headers=_hdr(USER_BOSS),
        json={"user_id": str(USER_DIRECTOR), "project_role": "coach", "status": "active"},
    )
    assert response.status_code == 403


# ---------------- 404 ----------------
async def test_unknown_project_404(client):
    r = await client.get(_settings(uuid.uuid4()), headers=_hdr(USER_BOSS))
    assert r.status_code == 404
    assert r.json()["detail"]["denied_reason"] == "project_not_found"


async def test_unknown_member_404(client):
    r = await client.patch(
        f"{_members(PROJECT_ALPHA)}/{uuid.uuid4()}",
        headers=_hdr(USER_BOSS),
        json={"status": "inactive"},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["denied_reason"] == "member_not_found"

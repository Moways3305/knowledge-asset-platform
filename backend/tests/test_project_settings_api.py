"""项目设置 / 项目成员管理 API 测试。

覆盖：读权限（成员 / 非成员 / admin / 治理角色）、写权限（pm / 治理可写，admin 只读，
consultant 成员只读）、wecom_group_id 安全展示与审计脱敏、成员角色/状态修改与 active
成员上下文、最后管理角色保护、未知 project/member 404、写审计安全无泄露。
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


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


_LEAK_TOKENS = [
    "wecom_user_id", "access_token", "oauth_state", "auth_code", "download_url",
    "storage_ref", "source_file_ref", "weknora", "token_hash", "app_secret", "ww_consultant",
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


async def test_admin_can_read_but_not_write(client):
    r = await client.get(_settings(PROJECT_ALPHA), headers=_hdr(USER_ADMIN_ONLY))
    assert r.status_code == 200, r.text
    assert r.json()["can_write"] is False
    w = await client.patch(
        _settings(PROJECT_ALPHA), headers=_hdr(USER_ADMIN_ONLY),
        json={"force_review_on_ingest": True},
    )
    assert w.status_code == 403
    assert w.json()["detail"]["denied_reason"] == "admin_business_permission_denied"


async def test_governance_can_read(client):
    for uid in (USER_BOSS, USER_DIRECTOR):
        r = await client.get(_settings(PROJECT_ALPHA), headers=_hdr(uid))
        assert r.status_code == 200
        assert r.json()["can_write"] is True


# ---------------- 写权限 ----------------
async def test_project_manager_can_update(client):
    r = await client.patch(
        _settings(PROJECT_ALPHA), headers=_hdr(USER_PROJECT_MANAGER),
        json={"lifecycle_route_key": "route_B", "lifecycle_phase_key": "行动辅导",
              "force_review_on_ingest": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["lifecycle_route_key"] == "route_B"
    assert body["force_review_on_ingest"] is True
    assert body["can_write"] is True


async def test_consultant_member_cannot_update(client):
    r = await client.patch(
        _settings(PROJECT_ALPHA), headers=_hdr(USER_CONSULTANT),
        json={"force_review_on_ingest": True},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "project_settings_write_forbidden"


async def test_boss_and_director_can_update(client):
    for uid, phase in ((USER_BOSS, "阶段评估"), (USER_DIRECTOR, "年度复盘")):
        r = await client.patch(
            _settings(PROJECT_ALPHA), headers=_hdr(uid),
            json={"lifecycle_phase_key": phase},
        )
        assert r.status_code == 200, r.text


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
        await db_session.execute(
            select(AuditEvent).where(AuditEvent.action == "project.settings_updated")
        )
    ).scalars().all()
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
    for k in ("member_id", "user_id", "name", "email", "company_roles", "project_role", "status", "wecom_bound", "source"):
        assert k in m
    _assert_no_leak(r.text)  # 不含 wecom_user_id 明文（ww_consultant...）


async def test_patch_member_then_not_in_active_context(client, db_session):
    lst = await client.get(_members(PROJECT_ALPHA), headers=_hdr(USER_BOSS))
    cons = next(m for m in lst.json()["items"] if m["user_id"] == str(USER_CONSULTANT))
    r = await client.patch(
        f"{_members(PROJECT_ALPHA)}/{cons['member_id']}", headers=_hdr(USER_BOSS),
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
        f"{_members(PROJECT_ALPHA)}/{pm['member_id']}", headers=_hdr(USER_BOSS),
        json={"status": "inactive"},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["denied_reason"] == "last_project_manager_protected"
    # 降级为 consultant 同样被保护。
    r2 = await client.patch(
        f"{_members(PROJECT_ALPHA)}/{pm['member_id']}", headers=_hdr(USER_BOSS),
        json={"project_role": "consultant"},
    )
    assert r2.status_code == 409


async def test_member_patch_writes_audit(client, db_session):
    # 先给 Alpha 加一个第二管理角色（coach），避免触发最后管理角色保护后再降级首个。
    # 这里直接改 USER_CONSULTANT（consultant）角色为 coach，再断言审计。
    lst = await client.get(_members(PROJECT_ALPHA), headers=_hdr(USER_BOSS))
    cons = next(m for m in lst.json()["items"] if m["user_id"] == str(USER_CONSULTANT))
    r = await client.patch(
        f"{_members(PROJECT_ALPHA)}/{cons['member_id']}",
        headers={**_hdr(USER_DIRECTOR), "X-Trace-Id": "trc-project-settings-member"},
        json={"project_role": "coach"},
    )
    assert r.status_code == 200, r.text
    rows = (
        await db_session.execute(
            select(AuditEvent).where(AuditEvent.action == "project.member_updated")
        )
    ).scalars().all()
    assert rows
    ev = rows[-1]
    assert ev.target_type == "project_member"
    assert (ev.extra or {}).get("target_user_id") == str(USER_CONSULTANT)
    assert (ev.after_snapshot or {}).get("project_role") == "coach"


# ---------------- 404 ----------------
async def test_unknown_project_404(client):
    r = await client.get(_settings(uuid.uuid4()), headers=_hdr(USER_BOSS))
    assert r.status_code == 404
    assert r.json()["detail"]["denied_reason"] == "project_not_found"


async def test_unknown_member_404(client):
    r = await client.patch(
        f"{_members(PROJECT_ALPHA)}/{uuid.uuid4()}", headers=_hdr(USER_BOSS),
        json={"status": "inactive"},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["denied_reason"] == "member_not_found"

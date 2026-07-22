"""项目归档 / 重新激活 / 删除 + 成员关系物理删除测试。

覆盖：
- 归档：仅总经理 / 咨询总监；归档联动停用全部成员；重复归档 409。
- 重新激活：仅治理；未归档时 409；成员保持 inactive。
- 删除：仅总经理；未归档 409；有资产 409；归档后空资产可删；物理删除关系 + KB 映射 + 项目行。
- 成员删除（项目域 + 人员域）：权限矩阵、保护规则（自己 / 最后一个 PM）、审计留痕。

不依赖真实外部系统；WeKnora 通过 dependency_overrides 注入 fake。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.main import app
from app.models.audit import AuditEvent
from app.models.identity import Project, ProjectMember, UserCompanyRole
from app.models.weknora import WeknoraKbMapping
from app.schemas.enums import KnowledgeScope
from app.seed.dev_seed import (
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_CONSULTANT_ADMIN,
    USER_DIRECTOR,
    USER_PROJECT_MANAGER,
)
from app.services.weknora_client import get_weknora_client

PROJECTS = "/api/v1/projects"
PEOPLE = "/api/v1/admin/people"


def _hdr(uid, trace=None):
    h = {"X-Dev-User-Id": str(uid)}
    if trace:
        h["X-Trace-Id"] = trace
    return h


def _create_project_body(name="归档测试项目", **over):
    base = {
        "name": name,
        "client_name": "示例客户",
        "project_manager_user_id": str(USER_PROJECT_MANAGER),
    }
    base.update(over)
    return base


class _FakeKbClient:
    """记录 delete_kb 调用；可模拟失败。"""

    def __init__(self, *, fail=False):
        self.fail = fail
        self.deleted: list[str] = []

    async def delete_kb(self, kb_id, *, trace_id=None, **_):
        if self.fail:
            raise RuntimeError("底座不可用")
        self.deleted.append(kb_id)


# ===================== 归档 =====================


async def test_boss_archives_project(client, db_session):
    r = await client.post(PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body())
    assert r.status_code == 201, r.text
    pid = uuid.UUID(r.json()["id"])

    r = await client.post(f"{PROJECTS}/{pid}/archive", headers=_hdr(USER_BOSS))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "archived"
    # 全部成员 → inactive。
    members = list(
        (await db_session.execute(select(ProjectMember).where(ProjectMember.project_id == pid)))
        .scalars()
        .all()
    )
    assert members and all(m.status == "inactive" for m in members)


async def test_director_archives_project(client):
    r = await client.post(
        PROJECTS, headers=_hdr(USER_DIRECTOR), json=_create_project_body("总监归档")
    )
    assert r.status_code == 201
    pid = uuid.UUID(r.json()["id"])
    r = await client.post(f"{PROJECTS}/{pid}/archive", headers=_hdr(USER_DIRECTOR))
    assert r.status_code == 200, r.text


async def test_consultant_cannot_archive(client):
    r = await client.post(
        PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("顾问无权归档")
    )
    pid = uuid.UUID(r.json()["id"])
    r = await client.post(f"{PROJECTS}/{pid}/archive", headers=_hdr(USER_CONSULTANT))
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "project_lifecycle_forbidden"


async def test_admin_cannot_archive(client):
    r = await client.post(
        PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("admin无权归档")
    )
    pid = uuid.UUID(r.json()["id"])
    r = await client.post(f"{PROJECTS}/{pid}/archive", headers=_hdr(USER_ADMIN_ONLY))
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "admin_business_permission_denied"


async def test_archive_already_archived_409(client):
    r = await client.post(PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("重复归档"))
    pid = uuid.UUID(r.json()["id"])
    assert (
        await client.post(f"{PROJECTS}/{pid}/archive", headers=_hdr(USER_BOSS))
    ).status_code == 200
    r = await client.post(f"{PROJECTS}/{pid}/archive", headers=_hdr(USER_BOSS))
    assert r.status_code == 409
    assert r.json()["detail"]["denied_reason"] == "project_already_archived"


async def test_archive_audit(client, db_session):
    r = await client.post(
        PROJECTS,
        headers={**_hdr(USER_BOSS), "X-Trace-Id": "trc-arc"},
        json=_create_project_body("归档审计"),
    )
    pid = uuid.UUID(r.json()["id"])
    await client.post(f"{PROJECTS}/{pid}/archive", headers=_hdr(USER_BOSS))
    evt = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "project.archived")
            )
        )
        .scalars()
        .first()
    )
    assert evt is not None and evt.actor_user_id == USER_BOSS
    assert evt.before_snapshot["status"] == "active"
    assert evt.after_snapshot["status"] == "archived"


# ===================== 重新激活 =====================


async def test_reactivate_after_archive(client, db_session):
    r = await client.post(PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("重新激活"))
    pid = uuid.UUID(r.json()["id"])
    await client.post(f"{PROJECTS}/{pid}/archive", headers=_hdr(USER_BOSS))
    r = await client.post(f"{PROJECTS}/{pid}/reactivate", headers=_hdr(USER_BOSS))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"
    # 成员保持 inactive。
    members = list(
        (await db_session.execute(select(ProjectMember).where(ProjectMember.project_id == pid)))
        .scalars()
        .all()
    )
    assert members and all(m.status == "inactive" for m in members)


async def test_reactivate_not_archived_409(client):
    r = await client.post(
        PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("未归档激活")
    )
    pid = uuid.UUID(r.json()["id"])
    r = await client.post(f"{PROJECTS}/{pid}/reactivate", headers=_hdr(USER_BOSS))
    assert r.status_code == 409
    assert r.json()["detail"]["denied_reason"] == "project_not_archived"


# ===================== 删除 =====================


async def _archive_project(client, pid):
    r = await client.post(f"{PROJECTS}/{pid}/archive", headers=_hdr(USER_BOSS))
    assert r.status_code == 200, r.text


async def test_delete_not_archived_409(client):
    r = await client.post(
        PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("未归档删除")
    )
    pid = uuid.UUID(r.json()["id"])
    r = await client.delete(f"{PROJECTS}/{pid}", headers=_hdr(USER_BOSS))
    assert r.status_code == 409
    assert r.json()["detail"]["denied_reason"] == "project_not_archived"


async def test_delete_with_assets_409(client, db_session):
    """项目下有未删除资产时拒绝删除（即使已归档）。"""
    from app.models.knowledge import KnowledgeAsset

    r = await client.post(
        PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("带资产删除")
    )
    pid = uuid.UUID(r.json()["id"])
    await _archive_project(client, pid)
    # 手动插入一条 project scope 资产（未删除）。
    asset = KnowledgeAsset(
        title="测试资产",
        scope=KnowledgeScope.project.value,
        zone="material",
        asset_type="deliverable",
        owner_user_id=USER_BOSS,
        project_id=pid,
        visibility="project_only",
        confidentiality_level="L2",
        ai_access_level="A2",
        asset_status="active",
    )
    db_session.add(asset)
    await db_session.commit()
    r = await client.delete(f"{PROJECTS}/{pid}", headers=_hdr(USER_BOSS))
    assert r.status_code == 409
    assert r.json()["detail"]["denied_reason"] == "project_has_assets"


async def test_delete_director_forbidden(client):
    r = await client.post(
        PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("总监无权删")
    )
    pid = uuid.UUID(r.json()["id"])
    await _archive_project(client, pid)
    r = await client.delete(f"{PROJECTS}/{pid}", headers=_hdr(USER_DIRECTOR))
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "project_delete_forbidden"


async def test_delete_admin_forbidden(client):
    r = await client.post(
        PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("admin无权删")
    )
    pid = uuid.UUID(r.json()["id"])
    await _archive_project(client, pid)
    r = await client.delete(f"{PROJECTS}/{pid}", headers=_hdr(USER_ADMIN_ONLY))
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "admin_business_permission_denied"


async def test_delete_archived_no_assets(client, db_session, monkeypatch):
    fake = _FakeKbClient()
    # 项目创建时不预建 KB（底座未启用），故无映射行；delete 仍应成功。
    r = await client.post(PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("可删项目"))
    pid = uuid.UUID(r.json()["id"])
    await _archive_project(client, pid)
    app.dependency_overrides[get_weknora_client] = lambda: fake
    try:
        r = await client.delete(f"{PROJECTS}/{pid}", headers=_hdr(USER_BOSS))
        assert r.status_code == 204, r.text
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)
    # 物理删除：project 行 + project_members 全部消失。
    assert await db_session.get(Project, pid) is None
    members = list(
        (await db_session.execute(select(ProjectMember).where(ProjectMember.project_id == pid)))
        .scalars()
        .all()
    )
    assert members == []


async def test_delete_audit_recorded(client, db_session, monkeypatch):
    fake = _FakeKbClient()
    r = await client.post(
        PROJECTS,
        headers={**_hdr(USER_BOSS), "X-Trace-Id": "trc-del"},
        json=_create_project_body("删除审计"),
    )
    pid = uuid.UUID(r.json()["id"])
    await _archive_project(client, pid)
    app.dependency_overrides[get_weknora_client] = lambda: fake
    try:
        await client.delete(f"{PROJECTS}/{pid}", headers=_hdr(USER_BOSS))
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)
    evt = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.action == "project.deleted")))
        .scalars()
        .first()
    )
    assert evt is not None and evt.actor_user_id == USER_BOSS
    assert evt.after_snapshot == {"deleted": True}


async def test_delete_clears_kb_mapping(client, db_session, monkeypatch):
    """归档项目删除后，weknora_kb_mappings（scope=project）行被清理；best-effort 调底座 delete_kb。"""
    fake = _FakeKbClient()
    r = await client.post(PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("删KB映射"))
    pid = uuid.UUID(r.json()["id"])
    await _archive_project(client, pid)
    # 手动插入一条 project KB 映射（绕过真实底座建库）。
    mapping = WeknoraKbMapping(
        scope=KnowledgeScope.project.value,
        owner_user_id=None,
        project_id=pid,
        weknora_kb_id="kb-to-delete",
        embedding_model_id="emb",
        kb_name="project_kb",
        status="active",
    )
    db_session.add(mapping)
    await db_session.commit()
    app.dependency_overrides[get_weknora_client] = lambda: fake
    try:
        r = await client.delete(f"{PROJECTS}/{pid}", headers=_hdr(USER_BOSS))
        assert r.status_code == 204, r.text
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)
    # 底座 delete_kb 被调用。
    assert fake.deleted == ["kb-to-delete"]
    # 映射行已删除。
    remaining = (
        (
            await db_session.execute(
                select(WeknoraKbMapping).where(WeknoraKbMapping.project_id == pid)
            )
        )
        .scalars()
        .all()
    )
    assert remaining == []


async def test_delete_kb_failure_does_not_block(client, db_session, monkeypatch):
    fake = _FakeKbClient(fail=True)
    r = await client.post(
        PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("底座删失败仍删")
    )
    pid = uuid.UUID(r.json()["id"])
    await _archive_project(client, pid)
    mapping = WeknoraKbMapping(
        scope=KnowledgeScope.project.value,
        owner_user_id=None,
        project_id=pid,
        weknora_kb_id="kb-fail",
        embedding_model_id="emb",
        kb_name="project_kb",
        status="active",
    )
    db_session.add(mapping)
    await db_session.commit()
    app.dependency_overrides[get_weknora_client] = lambda: fake
    try:
        r = await client.delete(f"{PROJECTS}/{pid}", headers=_hdr(USER_BOSS))
        assert r.status_code == 204, r.text  # best-effort，不阻断
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)
    assert await db_session.get(Project, pid) is None


# ===================== 项目域：成员物理删除 =====================


async def test_pm_removes_consultant_project_domain(client, db_session):
    r = await client.post(
        PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("PM删顾问域")
    )
    pid = uuid.UUID(r.json()["id"])
    # 找到 consultant 成员（PM 创建时只指定了 PM，需补一个 consultant）。
    r = await client.post(
        f"{PROJECTS}/{pid}/members",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={"user_id": str(USER_CONSULTANT), "project_role": "consultant", "status": "active"},
    )
    assert r.status_code == 201, r.text
    member_id = uuid.UUID(r.json()["member_id"])
    r = await client.delete(
        f"{PROJECTS}/{pid}/members/{member_id}", headers=_hdr(USER_PROJECT_MANAGER)
    )
    assert r.status_code == 204, r.text
    assert await db_session.get(ProjectMember, member_id) is None


async def test_cannot_remove_self_project_domain(client):
    r = await client.post(
        PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("删自己禁止")
    )
    pid = uuid.UUID(r.json()["id"])
    # 用列表接口拿到 PM 成员 id。
    lst = (await client.get(f"{PROJECTS}/{pid}/members", headers=_hdr(USER_PROJECT_MANAGER))).json()
    pm_member = next(m for m in lst["items"] if m["project_role"] == "project_manager")
    r = await client.delete(
        f"{PROJECTS}/{pid}/members/{pm_member['member_id']}",
        headers=_hdr(USER_PROJECT_MANAGER),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["denied_reason"] == "cannot_remove_self"


async def test_pm_cannot_remove_pm_project_domain(client):
    r = await client.post(
        PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("PM删PM禁止")
    )
    pid = uuid.UUID(r.json()["id"])
    lst = (await client.get(f"{PROJECTS}/{pid}/members", headers=_hdr(USER_BOSS))).json()
    pm_member = next(m for m in lst["items"] if m["project_role"] == "project_manager")
    # 顾问（非治理、非本项目 PM）尝试删除项目经理 → 应 403。
    r = await client.delete(
        f"{PROJECTS}/{pid}/members/{pm_member['member_id']}",
        headers=_hdr(USER_CONSULTANT),
    )
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "project_manager_removal_requires_governance"


async def test_boss_removes_pm_project_domain(client, db_session):
    """归档后 boss 可删除项目经理（项目 inactive 时不受最后一个 PM 保护）。"""
    r = await client.post(
        PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("boss删PM域")
    )
    pid = uuid.UUID(r.json()["id"])
    await _archive_project(client, pid)
    lst = (await client.get(f"{PROJECTS}/{pid}/members", headers=_hdr(USER_BOSS))).json()
    pm_member = next(m for m in lst["items"] if m["project_role"] == "project_manager")
    r = await client.delete(
        f"{PROJECTS}/{pid}/members/{pm_member['member_id']}", headers=_hdr(USER_BOSS)
    )
    assert r.status_code == 204, r.text
    assert await db_session.get(ProjectMember, uuid.UUID(pm_member["member_id"])) is None


async def test_cannot_remove_last_pm_when_active_project(client):
    r = await client.post(
        PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("最后一个PM保护")
    )
    pid = uuid.UUID(r.json()["id"])
    lst = (await client.get(f"{PROJECTS}/{pid}/members", headers=_hdr(USER_BOSS))).json()
    pm_member = next(m for m in lst["items"] if m["project_role"] == "project_manager")
    r = await client.delete(
        f"{PROJECTS}/{pid}/members/{pm_member['member_id']}", headers=_hdr(USER_BOSS)
    )
    assert r.status_code == 409
    assert r.json()["detail"]["denied_reason"] == "last_project_manager_protected"


async def test_can_remove_last_pm_after_archive(client):
    r = await client.post(
        PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("归档后删PM")
    )
    pid = uuid.UUID(r.json()["id"])
    await _archive_project(client, pid)
    lst = (await client.get(f"{PROJECTS}/{pid}/members", headers=_hdr(USER_BOSS))).json()
    pm_member = next(m for m in lst["items"] if m["project_role"] == "project_manager")
    r = await client.delete(
        f"{PROJECTS}/{pid}/members/{pm_member['member_id']}", headers=_hdr(USER_BOSS)
    )
    assert r.status_code == 204, r.text


async def test_member_removal_audit(client, db_session):
    r = await client.post(
        PROJECTS,
        headers={**_hdr(USER_BOSS), "X-Trace-Id": "trc-mbr-rm"},
        json=_create_project_body("删成员审计"),
    )
    pid = uuid.UUID(r.json()["id"])
    r = await client.post(
        f"{PROJECTS}/{pid}/members",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={"user_id": str(USER_CONSULTANT), "project_role": "consultant", "status": "active"},
    )
    member_id = r.json()["member_id"]
    await client.delete(f"{PROJECTS}/{pid}/members/{member_id}", headers=_hdr(USER_PROJECT_MANAGER))
    evt = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "people.project_membership_removed")
            )
        )
        .scalars()
        .first()
    )
    assert evt is not None and evt.after_snapshot == {"removed": True}


# ===================== 人员域：成员物理删除 =====================


async def test_people_domain_remove_membership(client, db_session):
    r = await client.post(
        PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("人员域删关系")
    )
    pid = uuid.UUID(r.json()["id"])
    r = await client.post(
        f"{PROJECTS}/{pid}/members",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={"user_id": str(USER_CONSULTANT), "project_role": "consultant", "status": "active"},
    )
    member_id = r.json()["member_id"]
    r = await client.delete(
        f"{PEOPLE}/{USER_CONSULTANT}/project-memberships/{member_id}",
        headers=_hdr(USER_PROJECT_MANAGER),
    )
    assert r.status_code == 204, r.text
    assert await db_session.get(ProjectMember, uuid.UUID(member_id)) is None


async def test_people_domain_admin_forbidden(client):
    r = await client.post(
        PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("admin无权删关系")
    )
    pid = uuid.UUID(r.json()["id"])
    r = await client.post(
        f"{PROJECTS}/{pid}/members",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={"user_id": str(USER_CONSULTANT), "project_role": "consultant", "status": "active"},
    )
    member_id = r.json()["member_id"]
    r = await client.delete(
        f"{PEOPLE}/{USER_CONSULTANT}/project-memberships/{member_id}",
        headers=_hdr(USER_ADMIN_ONLY),
    )
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "admin_business_permission_denied"


async def test_multi_role_session_uses_only_active_identity_for_manager_removal(client, db_session):
    """admin+boss defaults to admin; only an explicit server-side boss switch enables governance."""
    db_session.add(
        UserCompanyRole(
            user_id=USER_CONSULTANT_ADMIN,
            company_role="boss",
            status="active",
        )
    )
    await db_session.commit()

    created = await client.post(
        PROJECTS,
        headers=_hdr(USER_BOSS),
        json=_create_project_body("活动身份删项目经理"),
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]
    added = await client.post(
        f"{PROJECTS}/{project_id}/members",
        headers=_hdr(USER_BOSS),
        json={
            "user_id": str(USER_CONSULTANT),
            "project_role": "project_manager",
            "status": "active",
        },
    )
    assert added.status_code in (200, 201), added.text
    member_id = added.json()["member_id"]

    login = await client.post("/api/v1/auth/login", json={"email": "dual.f@dev.local"})
    assert login.status_code == 200
    assert login.json()["active_company_role"] == "admin"
    csrf = (await client.get("/api/v1/auth/csrf")).json()["csrf_token"]
    denied = await client.delete(
        f"{PEOPLE}/{USER_CONSULTANT}/project-memberships/{member_id}",
        headers={"X-CSRF-Token": csrf},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["denied_reason"] == "admin_business_permission_denied"

    switched = await client.post(
        "/api/v1/auth/active-company-role",
        headers={"X-CSRF-Token": csrf},
        json={"company_role": "boss"},
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["active_company_role"] == "boss"
    removed = await client.delete(
        f"{PEOPLE}/{USER_CONSULTANT}/project-memberships/{member_id}",
        headers={"X-CSRF-Token": csrf},
    )
    assert removed.status_code == 204, removed.text

    event = (
        (
            await db_session.execute(
                select(AuditEvent)
                .where(AuditEvent.action == "people.project_membership_removed")
                .order_by(AuditEvent.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    assert event is not None
    assert event.extra["active_work_identity"] == "boss"


async def test_people_domain_membership_not_found(client):
    r = await client.delete(
        f"{PEOPLE}/{USER_CONSULTANT}/project-memberships/{uuid.uuid4()}",
        headers=_hdr(USER_BOSS),
    )
    assert r.status_code == 404
    assert r.json()["detail"]["denied_reason"] == "membership_not_found"


# ===================== 归档影响 list_projects =====================


async def test_archived_project_not_in_list(client):
    r = await client.post(
        PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("归档不可见")
    )
    pid = uuid.UUID(r.json()["id"])
    await _archive_project(client, pid)
    # PM 重新激活前不在列表（status != active 过滤）。
    lst = (await client.get(PROJECTS, headers=_hdr(USER_PROJECT_MANAGER))).json()["items"]
    assert all(p["id"] != str(pid) for p in lst)

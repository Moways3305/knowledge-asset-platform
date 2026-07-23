"""项目删除 + 成员关系物理删除测试。

覆盖：
- 删除：仅有效项目经理；有资产 409；空项目可直接删除；物理删除关系 + KB 映射 + 项目行。
- 软删除资产不制造虚假计数，审计墓碑解绑后项目可删除。
- 成员删除（项目域 + 人员域）：权限矩阵、保护规则（自己 / 最后一个 PM）、审计留痕。

不依赖真实外部系统；WeKnora 通过 dependency_overrides 注入 fake。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db.utils import utc_now
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


def _create_project_body(name="项目删除测试", **over):
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


# ===================== 删除 =====================


async def test_boss_non_member_cannot_delete_project(client):
    r = await client.post(
        PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("总经理非项目经理")
    )
    pid = uuid.UUID(r.json()["id"])
    r = await client.delete(f"{PROJECTS}/{pid}", headers=_hdr(USER_BOSS))
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "project_delete_forbidden"


async def test_delete_with_assets_409(client, db_session):
    """项目下有未删除资产时拒绝项目经理删除。"""
    from app.models.knowledge import KnowledgeAsset

    r = await client.post(
        PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("带资产删除")
    )
    pid = uuid.UUID(r.json()["id"])
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
    r = await client.delete(f"{PROJECTS}/{pid}", headers=_hdr(USER_PROJECT_MANAGER))
    assert r.status_code == 409
    assert r.json()["detail"]["denied_reason"] == "project_has_assets"


async def test_soft_deleted_asset_does_not_block_readiness_or_project_delete(client, db_session):
    """软删除行已退出项目知识库，不再制造 0/1 计数矛盾或外键失败。"""
    from app.models.ingest import IngestTask
    from app.models.knowledge import KnowledgeAsset

    r = await client.post(
        PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("软删除资产项目")
    )
    pid = uuid.UUID(r.json()["id"])
    asset = KnowledgeAsset(
        title="已撤下测试资产",
        scope=KnowledgeScope.project.value,
        zone="material",
        asset_type="deliverable",
        owner_user_id=USER_BOSS,
        project_id=pid,
        visibility="project_only",
        confidentiality_level="L2",
        ai_access_level="A2",
        asset_status="deleted",
        deleted_at=utc_now(),
        deleted_by=USER_BOSS,
        delete_reason="回归测试",
    )
    db_session.add(asset)
    await db_session.flush()
    ingest = IngestTask(
        source="local_upload",
        source_file_ref="audit-only/source.docx",
        source_file_name="source.docx",
        status="completed",
        target_scope=KnowledgeScope.project.value,
        target_project_id=pid,
        result_asset_id=asset.id,
        created_by=USER_PROJECT_MANAGER,
    )
    db_session.add(ingest)
    await db_session.commit()

    readiness = await client.get(
        f"{PROJECTS}/{pid}/deletion-readiness", headers=_hdr(USER_PROJECT_MANAGER)
    )
    assert readiness.status_code == 200, readiness.text
    assert readiness.json()["asset_count"] == 0
    assert readiness.json()["can_delete"] is True
    assert "project_has_assets" not in readiness.json()["blockers"]

    deleted = await client.delete(f"{PROJECTS}/{pid}", headers=_hdr(USER_PROJECT_MANAGER))
    assert deleted.status_code == 204, deleted.text
    assert await db_session.get(Project, pid) is None
    await db_session.refresh(asset)
    assert asset.project_id is None
    await db_session.refresh(ingest)
    assert ingest.target_project_id is None


async def test_delete_director_forbidden(client):
    r = await client.post(
        PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("总监无权删")
    )
    pid = uuid.UUID(r.json()["id"])
    r = await client.delete(f"{PROJECTS}/{pid}", headers=_hdr(USER_DIRECTOR))
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "project_delete_forbidden"


async def test_delete_admin_forbidden(client):
    r = await client.post(
        PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("admin无权删")
    )
    pid = uuid.UUID(r.json()["id"])
    r = await client.delete(f"{PROJECTS}/{pid}", headers=_hdr(USER_ADMIN_ONLY))
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "admin_business_permission_denied"


async def test_project_manager_deletes_active_project_without_assets(
    client, db_session, monkeypatch
):
    fake = _FakeKbClient()
    # 项目创建时不预建 KB（底座未启用），故无映射行；delete 仍应成功。
    r = await client.post(PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("可删项目"))
    pid = uuid.UUID(r.json()["id"])
    app.dependency_overrides[get_weknora_client] = lambda: fake
    try:
        r = await client.delete(f"{PROJECTS}/{pid}", headers=_hdr(USER_PROJECT_MANAGER))
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
    app.dependency_overrides[get_weknora_client] = lambda: fake
    try:
        await client.delete(f"{PROJECTS}/{pid}", headers=_hdr(USER_PROJECT_MANAGER))
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)
    evt = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.action == "project.deleted")))
        .scalars()
        .first()
    )
    assert evt is not None and evt.actor_user_id == USER_PROJECT_MANAGER
    assert evt.after_snapshot == {"deleted": True}


async def test_delete_clears_kb_mapping(client, db_session, monkeypatch):
    """项目删除后，weknora_kb_mappings（scope=project）行被清理；best-effort 调底座 delete_kb。"""
    fake = _FakeKbClient()
    r = await client.post(PROJECTS, headers=_hdr(USER_BOSS), json=_create_project_body("删KB映射"))
    pid = uuid.UUID(r.json()["id"])
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
        r = await client.delete(f"{PROJECTS}/{pid}", headers=_hdr(USER_PROJECT_MANAGER))
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
        r = await client.delete(f"{PROJECTS}/{pid}", headers=_hdr(USER_PROJECT_MANAGER))
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

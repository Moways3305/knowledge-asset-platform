"""项目知识库创建测试。

仅 boss/咨询总监可创建，写真实 projects + active project_manager 成员，校验 PM 合法性，
重名冲突，审计无泄露；项目创建预建并初始化 project KB（best-effort，底座失败不阻断）。

（知识资产删除测试见 test_knowledge_delete.py。）
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.main import app
from app.models.audit import AuditEvent
from app.models.identity import Project, ProjectMember
from app.seed.dev_seed import (
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
    USER_PROJECT_MANAGER,
)
from app.services.weknora_client import get_weknora_client

PROJECTS = "/api/v1/projects"

_LEAK = [
    "storage_ref",
    "source_file_ref",
    "internal://",
    "wk-kb",
    "wk-doc",
    "kb_id",
    "doc_id",
    "chunk_id",
    "access_token",
    "download_url",
    "cookie",
    "ww_consultant",
    "sk-",
    "Bearer",
]


def _hdr(uid, trace=None):
    h = {"X-Dev-User-Id": str(uid)}
    if trace:
        h["X-Trace-Id"] = trace
    return h


def _assert_no_leak(text):
    for t in _LEAK:
        assert t not in text, f"不应泄露 {t}"


def _project_body(**over):
    base = {
        "name": "新建联调项目",
        "client_name": "示例客户",
        "project_manager_user_id": str(USER_CONSULTANT),
        "lifecycle_route_key": "route_A",
        "project_code": "NEW-26",
        "project_code_active": True,
        "naming_default_confidentiality": "L2",
    }
    base.update(over)
    return base


async def test_boss_creates_project(client, db_session):
    r = await client.post(PROJECTS, headers=_hdr(USER_BOSS), json=_project_body())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "新建联调项目"
    assert body["status"] == "active"
    assert body["project_manager_user_id"] == str(USER_CONSULTANT)
    _assert_no_leak(r.text)
    # 真实写入 projects + active project_manager 成员。
    pid = uuid.UUID(body["id"])
    proj = await db_session.get(Project, pid)
    assert proj is not None and proj.status == "active"
    pm = (
        (
            await db_session.execute(
                select(ProjectMember).where(
                    ProjectMember.project_id == pid,
                    ProjectMember.project_role == "project_manager",
                    ProjectMember.status == "active",
                )
            )
        )
        .scalars()
        .first()
    )
    assert pm is not None and pm.user_id == USER_CONSULTANT


async def test_director_creates_with_coach(client, db_session):
    r = await client.post(
        PROJECTS,
        headers=_hdr(USER_DIRECTOR),
        json=_project_body(
            name="带辅导老师项目",
            project_manager_user_id=str(USER_PROJECT_MANAGER),
            coach_user_id=str(USER_BOSS),
        ),
    )
    assert r.status_code == 201, r.text
    pid = uuid.UUID(r.json()["id"])
    roles = {
        m.project_role
        for m in (
            await db_session.execute(
                select(ProjectMember).where(
                    ProjectMember.project_id == pid, ProjectMember.status == "active"
                )
            )
        )
        .scalars()
        .all()
    }
    assert roles == {"project_manager", "coach"}


async def test_consultant_cannot_create(client):
    r = await client.post(PROJECTS, headers=_hdr(USER_CONSULTANT), json=_project_body())
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "project_create_forbidden"


async def test_admin_cannot_create(client):
    r = await client.post(PROJECTS, headers=_hdr(USER_ADMIN_ONLY), json=_project_body())
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "admin_business_permission_denied"


async def test_pm_not_business_422(client):
    """纯 admin 用户也可被任命为项目经理（由治理角色直接任命，不再校验业务角色）。"""
    r = await client.post(
        PROJECTS,
        headers=_hdr(USER_BOSS),
        json=_project_body(project_manager_user_id=str(USER_ADMIN_ONLY)),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == _project_body()["name"]
    assert str(body["project_manager_user_id"]) == str(USER_ADMIN_ONLY)


async def test_pm_not_found_422(client):
    r = await client.post(
        PROJECTS,
        headers=_hdr(USER_BOSS),
        json=_project_body(project_manager_user_id=str(uuid.uuid4())),
    )
    assert r.status_code == 422
    assert r.json()["detail"]["denied_reason"] == "project_manager_not_found"


async def test_duplicate_active_name_conflict_422(client):
    assert (
        await client.post(PROJECTS, headers=_hdr(USER_BOSS), json=_project_body(name="唯一名"))
    ).status_code == 201
    dup = await client.post(PROJECTS, headers=_hdr(USER_BOSS), json=_project_body(name="唯一名"))
    assert dup.status_code == 422
    assert dup.json()["detail"]["denied_reason"] == "project_name_conflict"


async def test_project_creation_requires_an_enabled_unique_project_code(client):
    disabled = await client.post(
        PROJECTS,
        headers=_hdr(USER_BOSS),
        json=_project_body(name="代码未启用项目", project_code_active=False),
    )
    assert disabled.status_code == 422
    assert disabled.json()["detail"]["denied_reason"] == "project_code_must_be_enabled"

    first = await client.post(
        PROJECTS,
        headers=_hdr(USER_BOSS),
        json=_project_body(name="项目代码甲", project_code="UNIQUE-26"),
    )
    assert first.status_code == 201, first.text
    duplicate = await client.post(
        PROJECTS,
        headers=_hdr(USER_BOSS),
        json=_project_body(name="项目代码乙", project_code="UNIQUE-26"),
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["detail"]["denied_reason"] == "project_code_conflict"


# ===== 项目创建预建并初始化 project KB（best-effort，不阻断） =====
class _FakeProjectKb:
    """记录建库 / 初始化；可模拟建库失败。"""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.created: list[str] = []
        self.initialized: list[str] = []
        self._n = 0

    async def create_kb(self, *, name, embedding_model_id, trace_id=None, **_):
        if self.fail:
            from app.services.weknora_client import WeKnoraError

            raise WeKnoraError("weknora_down", "底座不可用")
        self._n += 1
        kb_id = f"kb-proj-{self._n}"
        self.created.append(kb_id)
        return kb_id

    async def initialize_kb(self, kb_id, **_):
        self.initialized.append(kb_id)

    async def get_kb(self, kb_id, *, trace_id=None):
        return {
            "summary_model_id": "chat-test",
            "embedding_model_id": "test-embed",
            "chunking_config": {},
            "vlm_config": {},
            "asr_config": {},
            "storage_provider_config": {},
            "extract_config": {},
            "question_generation_config": {},
        }

    async def update_initialization_config(self, kb_id, *, config, trace_id=None):
        self.initialized.append(kb_id)
        return {"success": True}


async def test_create_project_precreates_kb(client, db_session, monkeypatch):
    from conftest import patch_default_model

    from app.models.weknora import WeknoraKbMapping

    fake = _FakeProjectKb()
    monkeypatch.setattr("app.services.weknora_client.weknora_enabled", lambda: True)
    patch_default_model(monkeypatch)
    app.dependency_overrides[get_weknora_client] = lambda: fake
    try:
        r = await client.post(
            PROJECTS, headers=_hdr(USER_BOSS), json=_project_body(name="预建KB项目")
        )
        assert r.status_code == 201, r.text
        pid = uuid.UUID(r.json()["id"])
        # 项目创建后 WeKnora 侧立即有对应 KB + 已初始化 + 映射 active。
        assert len(fake.created) == 1 and len(fake.initialized) == 1
        mapping = (
            await db_session.execute(
                select(WeknoraKbMapping).where(WeknoraKbMapping.project_id == pid)
            )
        ).scalar_one()
        assert mapping.status == "active"
        _assert_no_leak(r.text)  # 响应不外泄 kb_id
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_create_project_survives_kb_failure(client, db_session, monkeypatch):
    from app.core.config import get_settings

    fake = _FakeProjectKb(fail=True)
    monkeypatch.setattr("app.services.weknora_client.weknora_enabled", lambda: True)
    monkeypatch.setattr(get_settings(), "weknora_embedding_model_id", "test-embed")
    app.dependency_overrides[get_weknora_client] = lambda: fake
    try:
        r = await client.post(
            PROJECTS, headers=_hdr(USER_BOSS), json=_project_body(name="底座失败仍建项目")
        )
        # 底座失败不阻断项目创建。
        assert r.status_code == 201, r.text
        pid = uuid.UUID(r.json()["id"])
        proj = await db_session.get(Project, pid)
        assert proj is not None and proj.status == "active"
        _assert_no_leak(r.text)
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_create_project_no_active_kb_when_embedding_missing(client, db_session, monkeypatch):
    """底座启用但 embedding 未配 → 项目仍创建，但不写 active 假映射。"""
    from app.core.config import get_settings
    from app.models.weknora import WeknoraKbMapping

    fake = _FakeProjectKb()  # 不会被调用到（embedding 守卫在建库前 fail-closed）
    monkeypatch.setattr("app.services.weknora_client.weknora_enabled", lambda: True)
    monkeypatch.setattr(get_settings(), "weknora_embedding_model_id", "")
    app.dependency_overrides[get_weknora_client] = lambda: fake
    try:
        r = await client.post(
            PROJECTS, headers=_hdr(USER_BOSS), json=_project_body(name="缺embedding仍建项目")
        )
        assert r.status_code == 201, r.text
        pid = uuid.UUID(r.json()["id"])
        proj = await db_session.get(Project, pid)
        assert proj is not None and proj.status == "active"
        # 未建 KB、未写任何 project 映射（不产生 active 假成功）。
        assert fake.created == []
        mapping = (
            await db_session.execute(
                select(WeknoraKbMapping).where(WeknoraKbMapping.project_id == pid)
            )
        ).scalar_one_or_none()
        assert mapping is None
        _assert_no_leak(r.text)
    finally:
        app.dependency_overrides.pop(get_weknora_client, None)


async def test_created_project_visible_in_lists(client):
    created = (
        await client.post(
            PROJECTS,
            headers=_hdr(USER_BOSS),
            json=_project_body(
                name="可见性项目", project_manager_user_id=str(USER_PROJECT_MANAGER)
            ),
        )
    ).json()
    pid = created["id"]
    # 公司治理身份不扩展项目可见范围；创建人不是成员时不可枚举。
    boss_list = (await client.get(PROJECTS, headers=_hdr(USER_BOSS))).json()["items"]
    assert all(p["id"] != pid for p in boss_list)
    # PM 在自己的项目列表可见，且对项目设置可读。
    pm_list = (await client.get(PROJECTS, headers=_hdr(USER_PROJECT_MANAGER))).json()["items"]
    assert any(p["id"] == pid for p in pm_list)
    assert (
        await client.get(f"{PROJECTS}/{pid}/settings", headers=_hdr(USER_PROJECT_MANAGER))
    ).status_code == 200


async def test_project_create_audit_no_leak(client, db_session):
    await client.post(
        PROJECTS,
        headers={**_hdr(USER_BOSS), "X-Trace-Id": "trc-proj"},
        json=_project_body(name="审计项目"),
    )
    evt = (
        (await db_session.execute(select(AuditEvent).where(AuditEvent.action == "project.created")))
        .scalars()
        .first()
    )
    assert evt is not None and evt.actor_user_id == USER_BOSS
    assert evt.after_snapshot["name"] == "审计项目"
    _assert_no_leak(f"{evt.before_snapshot}{evt.after_snapshot}{evt.extra}")

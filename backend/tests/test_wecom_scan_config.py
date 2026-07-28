from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.main import app
from app.models.identity import Project, User
from app.models.wecom import WecomProjectScanSpace, WecomScanConfig
from app.seed.dev_seed import (
    PROJECT_ALPHA,
    PROJECT_BETA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_PROJECT_MANAGER,
)
from app.services.wecom_client import WeComError, get_wecom_drive_client
from app.services.wecom_scan import _ensure_project_scan_space

CONFIGS = "/api/v1/admin/wecom-scan/configs"
PROJECTS = "/api/v1/admin/wecom-scan/project-options"


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


def _body(project_id=PROJECT_ALPHA):
    return {
        "name": "项目资料扫描",
        "target_project_id": str(project_id),
        "task_owner_user_id": str(USER_CONSULTANT),
        "enabled": True,
    }


class FakeDrive:
    def __init__(self, *, error: WeComError | None = None, create_delay: float = 0):
        self.error = error
        self.create_delay = create_delay
        self.created: list[tuple[str, list[str]]] = []
        self.list_calls: list[str] = []

    async def create_project_space(self, *, space_name: str, manager_user_ids: list[str]):
        self.created.append((space_name, manager_user_ids))
        if self.create_delay:
            await asyncio.sleep(self.create_delay)
        if self.error:
            raise self.error
        return f"server-space-{len(self.created)}"

    async def list_files(self, directory_path: str):
        self.list_calls.append(directory_path)
        return []

    async def download_file(self, file_id: str):
        return b""


async def test_project_manager_only_sees_and_operates_managed_project(client):
    drive = FakeDrive()
    app.dependency_overrides[get_wecom_drive_client] = lambda: drive

    created = await client.post(CONFIGS, headers=_hdr(USER_PROJECT_MANAGER), json=_body())
    assert created.status_code == 201, created.text
    out = created.json()
    assert out["scope_type"] == "project"
    assert out["related_project_id"] == str(PROJECT_ALPHA)
    assert out["scan_space_status"] == "ready"
    assert out["manager_access_status"] == "identity_link_required"
    assert "directory_path" not in out
    assert "spaceid" not in created.text

    options = await client.get(PROJECTS, headers=_hdr(USER_PROJECT_MANAGER))
    assert [item["id"] for item in options.json()["items"]] == [str(PROJECT_ALPHA)]

    cross = await client.post(CONFIGS, headers=_hdr(USER_PROJECT_MANAGER), json=_body(PROJECT_BETA))
    assert cross.status_code == 404
    assert (await client.get(CONFIGS, headers=_hdr(USER_CONSULTANT))).status_code == 403


async def test_project_space_is_reused_and_only_mapped_managers_are_added(client, db_session):
    manager = await db_session.get(User, USER_PROJECT_MANAGER)
    manager.wecom_user_id = "ww_project_manager"
    await db_session.commit()
    drive = FakeDrive()
    app.dependency_overrides[get_wecom_drive_client] = lambda: drive

    first = await client.post(CONFIGS, headers=_hdr(USER_ADMIN_ONLY), json=_body())
    second = await client.post(
        CONFIGS,
        headers=_hdr(USER_ADMIN_ONLY),
        json={**_body(), "name": "第二个配置"},
    )
    assert first.status_code == second.status_code == 201
    assert len(drive.created) == 1
    assert drive.created[0][1] == ["ww_project_manager"]
    assert "ww_consultant_a" not in drive.created[0][1]


async def test_concurrent_project_space_claim_calls_space_create_once(tmp_path):
    database_path = (tmp_path / "wecom-concurrency.db").as_posix()
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        session.add(Project(id=PROJECT_ALPHA, name="Alpha 项目", status="active"))
        await session.commit()

    drive = FakeDrive(create_delay=0.15)

    async def ensure():
        async with maker() as session:
            project = await session.get(Project, PROJECT_ALPHA)
            assert project is not None
            return await _ensure_project_scan_space(
                session, project=project, drive=drive, trace_id="concurrent-test"
            )

    first, second = await asyncio.gather(ensure(), ensure())
    assert first.status == second.status == "ready"
    assert first.space_id == second.space_id
    assert len(drive.created) == 1
    await engine.dispose()


async def test_legacy_directory_never_bypasses_project_space_mapping(client, db_session):
    legacy = WecomScanConfig(
        name="历史目录配置",
        directory_path="spaceid:legacy-space;fatherid:legacy-folder",
        scope_type="project",
        related_project_id=PROJECT_ALPHA,
        enabled=True,
        created_by=USER_CONSULTANT,
    )
    db_session.add(legacy)
    await db_session.commit()
    drive = FakeDrive()
    app.dependency_overrides[get_wecom_drive_client] = lambda: drive

    response = await client.post(f"{CONFIGS}/{legacy.id}/scan", headers=_hdr(USER_ADMIN_ONLY))
    assert response.status_code == 200
    assert response.json()["scan_status"] == "failed"
    assert response.json()["error_type"] == "wecom_project_scan_space_unavailable"
    assert drive.list_calls == []


async def test_safe_space_failure_category_and_persistent_unavailable_state(client, db_session):
    drive = FakeDrive(
        error=WeComError(
            "wecom_drive_permission_denied",
            "raw errmsg token=secret",
            stage="space_create",
            upstream_errcode=48002,
        )
    )
    app.dependency_overrides[get_wecom_drive_client] = lambda: drive
    response = await client.post(CONFIGS, headers=_hdr(USER_ADMIN_ONLY), json=_body())
    assert response.status_code == 502
    assert response.json()["detail"]["denied_reason"] == "wecom_drive_permission_denied"
    assert "协作-微盘-API" in response.text
    assert "token=secret" not in response.text
    mapping = (
        await db_session.execute(
            select(WecomProjectScanSpace).where(WecomProjectScanSpace.project_id == PROJECT_ALPHA)
        )
    ).scalar_one()
    assert mapping.status == "unavailable"
    assert mapping.last_error_code == "wecom_drive_permission_denied"
    assert mapping.space_id is None


async def test_governance_keeps_cross_project_read(client):
    response = await client.get(PROJECTS, headers=_hdr(USER_BOSS))
    assert response.status_code == 200
    assert {item["id"] for item in response.json()["items"]} == {
        str(PROJECT_ALPHA),
        str(PROJECT_BETA),
    }

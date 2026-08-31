"""Formal-directory naming contracts and legacy configuration compatibility."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.identity import Project
from app.seed.dev_seed import PROJECT_ALPHA, USER_BOSS, USER_CONSULTANT, USER_PROJECT_MANAGER


def _hdr(user_id: uuid.UUID) -> dict[str, str]:
    return {"X-Dev-User-Id": str(user_id)}


def _config(*, with_legacy_category: bool = False) -> dict:
    return {
        "schema_version": 2,
        "enforced": True,
        # These fields remain readable historical configuration only. Publishing
        # a directory revision must not project either one back into projects.
        "project_codes": [],
        "categories": (
            [
                {
                    "id": str(uuid.uuid4()),
                    "scope": "project",
                    "primary": "历史项目资料",
                    "secondary": "历史交付件",
                    "prefix": "历史交付件",
                    "asset_type": None,
                    "default_confidentiality": "L2",
                    "enabled": True,
                    "sort_order": 10,
                }
            ]
            if with_legacy_category
            else []
        ),
        "directories": [
            {
                "directory_key": "project.deliverables",
                "scope": "project",
                "display_name": "03 交付成果",
                "description": "诊断 / 战略 / 方案",
                "naming_code": "交付成果",
                "default_confidentiality": "L3",
                "enabled": True,
                "sort_order": 30,
            },
            {
                "directory_key": "company.methodology",
                "scope": "company",
                "display_name": "02 方法论",
                "description": "模型与工具",
                "naming_code": "方法论",
                "default_confidentiality": "L2",
                "enabled": True,
                "sort_order": 20,
            },
        ],
    }


async def _publish(client, *, with_legacy_category: bool = False) -> None:
    saved = await client.put(
        "/api/v1/admin/naming-rules/draft",
        headers=_hdr(USER_BOSS),
        json={
            "expected_base_version": 1,
            "directories": _config(with_legacy_category=with_legacy_category)["directories"],
        },
    )
    assert saved.status_code == 200, saved.text
    published = await client.post(
        "/api/v1/admin/naming-rules/publish",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": 1},
    )
    assert published.status_code == 200, published.text


async def _enable_project_code(client, code: str = "ALPHA-NEW") -> None:
    response = await client.patch(
        f"/api/v1/projects/{PROJECT_ALPHA}/settings",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "project_code": code,
            "project_code_active": True,
            "naming_default_confidentiality": "L3",
        },
    )
    assert response.status_code == 200, response.text


async def _upload(client, user_id: uuid.UUID = USER_PROJECT_MANAGER) -> str:
    response = await client.post(
        "/api/v1/ingest/upload",
        headers=_hdr(user_id),
        files={"file": ("source.txt", b"formal directory source body", "text/plain")},
    )
    assert response.status_code == 200, response.text
    return response.json()["ingest_task_id"]


async def test_options_expose_only_scoped_formal_directories(client):
    await _enable_project_code(client)
    await _publish(client)

    response = await client.get(
        "/api/v1/naming-options",
        headers=_hdr(USER_PROJECT_MANAGER),
        params={"scope": "project", "project_id": str(PROJECT_ALPHA)},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "categories" not in payload
    assert payload["directories"] == [
        {
            "directory_key": "project.deliverables",
            "scope": "project",
            "display_name": "03 交付成果",
            "description": "诊断 / 战略 / 方案",
            "sort_order": 30,
            "enabled": True,
        }
    ]


async def test_direct_directory_generates_project_name_without_category_metadata(client):
    await _enable_project_code(client)
    await _publish(client)
    task_id = await _upload(client)

    response = await client.post(
        f"/api/v1/ingest/{task_id}/naming-preview",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "confidentiality_level": "L3",
            "naming": {
                "directory_key": "project.deliverables",
                "subject": "年度战略复盘",
                "formed_on": "2026-08-31",
                "version": "V1",
            },
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["canonical_name"].startswith("【ALPHA-NEW-2026-交付成果】")
    assert payload["fields"]["directory_key"] == "project.deliverables"
    assert "category_id" not in payload["fields"]
    assert "asset_type" not in payload["fields"]


async def test_directory_scope_is_validated_server_side(client):
    await _enable_project_code(client)
    await _publish(client)
    task_id = await _upload(client)
    response = await client.post(
        f"/api/v1/ingest/{task_id}/naming-preview",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "confidentiality_level": "L2",
            "naming": {
                "directory_key": "company.methodology",
                "subject": "错误范围",
                "formed_on": "2026-08-31",
                "version": "V1",
            },
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["denied_reason"] == "directory_scope_mismatch"


async def test_company_preview_requires_governance_and_applicable_to(client):
    await _publish(client)
    task_id = await _upload(client, USER_CONSULTANT)
    naming = {
        "directory_key": "company.methodology",
        "subject": "项目方法沉淀",
        "formed_on": "2026-08-31",
        "version": "V1",
        "applicable_to": "全公司",
    }
    denied = await client.post(
        f"/api/v1/ingest/{task_id}/naming-preview",
        headers=_hdr(USER_CONSULTANT),
        json={
            "target_scope": "company",
            "confidentiality_level": "L2",
            "naming": naming,
        },
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["denied_reason"] == "company_confirmation_requires_governance"

    allowed = await client.post(
        f"/api/v1/ingest/{task_id}/naming-preview",
        headers=_hdr(USER_BOSS),
        json={
            "target_scope": "company",
            "confidentiality_level": "L2",
            "naming": naming,
        },
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["canonical_name"].startswith("【方法论】")


async def test_legacy_category_input_is_read_only_and_does_not_rewrite_project_code(
    client, db_session
):
    await _enable_project_code(client, "DIRECT-26")
    await _publish(client, with_legacy_category=True)

    project = await db_session.scalar(select(Project).where(Project.id == PROJECT_ALPHA))
    assert project is not None
    await db_session.refresh(project)
    assert project.project_code == "DIRECT-26"
    assert project.project_code_active is True

    center = await client.get("/api/v1/admin/naming-rules", headers=_hdr(USER_BOSS))
    assert center.status_code == 200
    assert center.json()["published"]["config"]["categories"] == []

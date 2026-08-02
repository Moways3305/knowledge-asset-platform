"""Governed naming rules and server-authoritative confirmation previews."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.seed.dev_seed import (
    PROJECT_ALPHA,
    PROJECT_BETA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_PROJECT_MANAGER,
)


def _hdr(user_id: uuid.UUID) -> dict[str, str]:
    return {"X-Dev-User-Id": str(user_id)}


def _config(category_id: uuid.UUID, *, duplicate_code: bool = False) -> dict:
    return {
        "schema_version": 1,
        "enforced": True,
        "project_codes": [
            {
                "project_id": str(PROJECT_ALPHA),
                "code": "ALPHA-26",
                "enabled": True,
                "default_confidentiality": "L2",
            },
            *(
                [
                    {
                        "project_id": str(PROJECT_BETA),
                        "code": "ALPHA-26",
                        "enabled": False,
                        "default_confidentiality": "L2",
                    }
                ]
                if duplicate_code
                else []
            ),
        ],
        "categories": [
            {
                "id": str(category_id),
                "scope": "project",
                "primary": "项目资料",
                "secondary": "交付件",
                "prefix": "项目资料-交付件",
                "default_confidentiality": "L2",
                "enabled": True,
                "sort_order": 10,
            }
        ],
    }


async def _publish(client, category_id: uuid.UUID) -> None:
    saved = await client.put(
        "/api/v1/admin/naming-rules/draft",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": 1, "config": _config(category_id)},
    )
    assert saved.status_code == 200
    published = await client.post(
        "/api/v1/admin/naming-rules/publish",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": 1},
    )
    assert published.status_code == 200


async def _upload(client) -> str:
    response = await client.post(
        "/api/v1/ingest/upload",
        headers=_hdr(USER_PROJECT_MANAGER),
        files={"file": ("source.txt", b"naming rule source body", "text/plain")},
    )
    assert response.status_code == 200
    return response.json()["ingest_task_id"]


async def test_rule_center_is_governance_only_and_draft_is_not_live(client):
    denied = await client.get("/api/v1/admin/naming-rules", headers=_hdr(USER_ADMIN_ONLY))
    assert denied.status_code == 403
    assert denied.json()["detail"]["denied_reason"] == "naming_rule_governance_required"

    center = await client.get("/api/v1/admin/naming-rules", headers=_hdr(USER_BOSS))
    assert center.status_code == 200
    assert center.json()["published"]["config"]["enforced"] is False

    category_id = uuid.uuid4()
    saved = await client.put(
        "/api/v1/admin/naming-rules/draft",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": 1, "config": _config(category_id)},
    )
    assert saved.status_code == 200

    options = await client.get(
        "/api/v1/naming-options",
        headers=_hdr(USER_PROJECT_MANAGER),
        params={"scope": "project", "project_id": str(PROJECT_ALPHA)},
    )
    assert options.status_code == 200
    assert options.json()["required"] is False


async def test_project_codes_are_unique_in_draft_validation(client):
    response = await client.put(
        "/api/v1/admin/naming-rules/draft",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": 1, "config": _config(uuid.uuid4(), duplicate_code=True)},
    )
    assert response.status_code == 422


async def test_publish_activates_preview_and_confirmation_recomputes_name(client, db_session):
    category_id = uuid.uuid4()
    await _publish(client, category_id)
    task_id = await _upload(client)

    preview = await client.post(
        f"/api/v1/ingest/{task_id}/naming-preview",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "confidentiality_level": "L2",
            "naming": {
                "category_id": str(category_id),
                "subject": "预览主题",
                "formed_on": "2026-08-02",
                "version": "V1",
            },
        },
    )
    assert preview.status_code == 200
    assert preview.json()["canonical_name"] == "【ALPHA-26-2026-交付件】预览主题_20260802_V1_L2.txt"

    confirmed = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "title": "最终标题",
            "summary": "最终摘要",
            "tags": [],
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "target_zone": "material",
            "asset_type": "methodology",
            "confidentiality_level": "L2",
            "ai_access_level": "A2",
            "lifecycle_phase_key": "delivery",
            "naming": {
                "category_id": str(category_id),
                "subject": "最终主题",
                "formed_on": "2026-08-02",
                "version": "V2",
                "canonical_name": "client-controlled.exe",
            },
        },
    )
    assert confirmed.status_code == 200
    canonical = "【ALPHA-26-2026-交付件】最终主题_20260802_V2_L2.txt"
    assert confirmed.json()["canonical_name"] == canonical

    asset = await db_session.scalar(
        select(KnowledgeAsset).where(
            KnowledgeAsset.id == uuid.UUID(confirmed.json()["result_asset_id"])
        )
    )
    version = await db_session.scalar(
        select(KnowledgeAssetVersion).where(KnowledgeAssetVersion.id == asset.current_version_id)
    )
    assert asset.canonical_name == canonical
    assert version.naming_rule_version == 2
    assert version.naming_metadata["canonical_name"] == canonical


async def test_publish_conflict_is_stable(client):
    response = await client.post(
        "/api/v1/admin/naming-rules/publish",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": 999},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["denied_reason"] == "naming_rule_publish_conflict"

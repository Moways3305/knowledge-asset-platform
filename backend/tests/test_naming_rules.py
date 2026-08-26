"""Governed naming rules and server-authoritative confirmation previews."""

from __future__ import annotations

import asyncio
import json
import uuid

from sqlalchemy import select

from app.main import app
from app.models.audit import AuditEvent
from app.models.identity import ProjectMember
from app.models.ingest import IngestTaskAiResult
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.review import ReviewTask
from app.schemas.enums import AuditAction
from app.seed.dev_seed import (
    PROJECT_ALPHA,
    PROJECT_BETA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_PROJECT_MANAGER,
)
from app.services.generation_models import get_generation_llm_client
from app.services.llm_client import NullLLMClient


def _hdr(user_id: uuid.UUID) -> dict[str, str]:
    return {"X-Dev-User-Id": str(user_id)}


def _config(
    category_id: uuid.UUID,
    *,
    duplicate_code: bool = False,
    code: str = "ALPHA-26",
    client_aliases: list[str] | None = None,
    client_aliases_enabled: bool = True,
    category: str = "交付件",
    company_category_id: uuid.UUID | None = None,
) -> dict:
    return {
        "schema_version": 2,
        "enforced": True,
        "project_codes": [
            {
                "project_id": str(PROJECT_ALPHA),
                "code": code,
                "enabled": True,
                "default_confidentiality": "L2",
                "client_aliases": client_aliases or [],
                "client_aliases_enabled": client_aliases_enabled,
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
                "secondary": category,
                "prefix": f"项目资料-{category}",
                "default_confidentiality": "L2",
                "asset_type": "deliverable",
                "enabled": True,
                "sort_order": 10,
            },
            *(
                [
                    {
                        "id": str(company_category_id),
                        "scope": "company",
                        "primary": "公司制度",
                        "secondary": "年度计划",
                        "prefix": "公司制度-年度计划",
                        "default_confidentiality": "L2",
                        "asset_type": "methodology",
                        "enabled": True,
                        "sort_order": 20,
                    }
                ]
                if company_category_id is not None
                else []
            ),
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


async def _upload(client, user_id: uuid.UUID = USER_PROJECT_MANAGER) -> str:
    response = await client.post(
        "/api/v1/ingest/upload",
        headers=_hdr(user_id),
        files={"file": ("source.txt", b"naming rule source body", "text/plain")},
    )
    assert response.status_code == 200
    return response.json()["ingest_task_id"]


def _warning_codes(payload: dict) -> list[str]:
    return [notice["code"] for notice in payload.get("notices", [])]


class _CategoryLLM:
    provider = "test"
    model = "category-test"

    def __init__(self, category_id: uuid.UUID | None, confidence: str = "high") -> None:
        self.category_id = category_id
        self.confidence = confidence
        self.messages: list[list[dict[str, str]]] = []

    async def chat_completion(self, messages, **_kwargs) -> str:
        self.messages.append(messages)
        return json.dumps(
            {
                "suggested_category_id": str(self.category_id) if self.category_id else None,
                "category_confidence": self.confidence,
            }
        )


class _RawCategoryLLM:
    provider = "test"
    model = "category-test"

    def __init__(self, raw: str) -> None:
        self.raw = raw

    async def chat_completion(self, _messages, **_kwargs) -> str:
        return self.raw


class _BatchCategoryLLM:
    provider = "test"
    model = "category-test"

    def __init__(self, category_id: uuid.UUID) -> None:
        self.category_id = category_id
        self.messages: list[list[dict[str, str]]] = []

    async def chat_completion(self, messages, **_kwargs) -> str:
        self.messages.append(messages)
        body = json.loads(messages[1]["content"])
        return json.dumps(
            {
                "items": [
                    {
                        "task_id": item["task_id"],
                        "suggested_category_id": str(self.category_id),
                        "category_confidence": "high",
                    }
                    for item in body["documents"]
                ]
            }
        )


class _PartialBatchCategoryLLM(_BatchCategoryLLM):
    async def chat_completion(self, messages, **_kwargs) -> str:
        self.messages.append(messages)
        documents = json.loads(messages[1]["content"])["documents"]
        returned = documents[:-1] if len(documents) > 1 else documents
        return json.dumps(
            {
                "items": [
                    {
                        "task_id": item["task_id"],
                        "suggested_category_id": str(self.category_id),
                        "category_confidence": "high",
                    }
                    for item in returned
                ]
            }
        )


class _CombinedGenerationCategoryLLM:
    provider = "test"
    model = "combined-generation-category"

    def __init__(self, category_id: uuid.UUID) -> None:
        self.category_id = category_id
        self.calls = 0
        self.messages: list[list[dict[str, str]]] = []

    async def chat_completion(self, messages, **_kwargs) -> str:
        self.calls += 1
        self.messages.append(messages)
        return json.dumps(
            {
                "topic": "项目复盘",
                "one_liner": "项目复盘知识摘要",
                "detailed": "项目复盘内容、经验与改进建议。",
                "key_points": ["经验", "改进"],
                "tags": ["复盘"],
                "confidentiality_level": "L2",
                "confidentiality_confidence": "medium",
                "category_suggestions": {
                    "project": {
                        "suggested_category_id": str(self.category_id),
                        "category_confidence": "high",
                    }
                },
            },
            ensure_ascii=False,
        )


class _BlockingCategoryLLM(_CategoryLLM):
    def __init__(self, category_id: uuid.UUID) -> None:
        super().__init__(category_id)
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def chat_completion(self, messages, **kwargs) -> str:
        self.started.set()
        await self.release.wait()
        return await super().chat_completion(messages, **kwargs)


async def _publish_categories(client, categories: list[tuple[uuid.UUID, str]]) -> None:
    config = _config(categories[0][0], category=categories[0][1])
    config["categories"] = [
        {
            "id": str(category_id),
            "scope": "project",
            "primary": "项目资料",
            "secondary": secondary,
            "prefix": f"项目资料-{secondary}",
            "default_confidentiality": "L2",
            "asset_type": "deliverable",
            "enabled": True,
            "sort_order": index * 10,
        }
        for index, (category_id, secondary) in enumerate(categories, start=1)
    ]
    saved = await client.put(
        "/api/v1/admin/naming-rules/draft",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": 1, "config": config},
    )
    assert saved.status_code == 200, saved.text
    published = await client.post(
        "/api/v1/admin/naming-rules/publish",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": 1},
    )
    assert published.status_code == 200, published.text


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


async def test_all_projects_share_categories_but_keep_project_codes(client, db_session):
    category_id = uuid.uuid4()
    config = _config(category_id)
    config["project_codes"].append(
        {
            "project_id": str(PROJECT_BETA),
            "code": "BETA-26",
            "enabled": True,
            "default_confidentiality": "L3",
        }
    )
    saved = await client.put(
        "/api/v1/admin/naming-rules/draft",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": 1, "config": config},
    )
    assert saved.status_code == 200, saved.text
    assert (
        await client.post(
            "/api/v1/admin/naming-rules/publish",
            headers=_hdr(USER_BOSS),
            json={"expected_base_version": 1},
        )
    ).status_code == 200

    options = await client.get(
        "/api/v1/naming-options",
        headers=_hdr(USER_PROJECT_MANAGER),
        params={"scope": "project", "project_id": str(PROJECT_ALPHA)},
    )
    assert options.status_code == 200
    alpha_ids = {item["id"] for item in options.json()["categories"]}
    db_session.add(
        ProjectMember(
            user_id=USER_PROJECT_MANAGER,
            project_id=PROJECT_BETA,
            project_role="project_manager",
            status="active",
        )
    )
    await db_session.commit()
    beta_options = await client.get(
        "/api/v1/naming-options",
        headers=_hdr(USER_PROJECT_MANAGER),
        params={"scope": "project", "project_id": str(PROJECT_BETA)},
    )
    assert beta_options.status_code == 200
    beta_ids = {item["id"] for item in beta_options.json()["categories"]}
    assert alpha_ids == beta_ids == {str(category_id)}

    task_id = await _upload(client)
    preview = await client.post(
        f"/api/v1/ingest/{task_id}/naming-preview",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "target_scope": "project",
            "target_project_id": str(PROJECT_BETA),
            "confidentiality_level": "L3",
            "naming": {
                "category_id": str(category_id),
                "subject": "统一规则验证",
                "formed_on": "2026-08-10",
                "version": "V1",
            },
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["canonical_name"].startswith("【BETA-26-2026-")


async def test_category_scope_and_enabled_state_still_fail_closed(client):
    project_category_id = uuid.uuid4()
    disabled_category_id = uuid.uuid4()
    company_category_id = uuid.uuid4()
    config = _config(project_category_id, company_category_id=company_category_id)
    config["categories"].append(
        {
            "id": str(disabled_category_id),
            "scope": "project",
            "primary": "项目资料",
            "secondary": "项目复盘",
            "prefix": "项目复盘",
            "default_confidentiality": "L2",
            "enabled": False,
            "sort_order": 30,
        }
    )
    saved = await client.put(
        "/api/v1/admin/naming-rules/draft",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": 1, "config": config},
    )
    assert saved.status_code == 200, saved.text
    assert (
        await client.post(
            "/api/v1/admin/naming-rules/publish",
            headers=_hdr(USER_BOSS),
            json={"expected_base_version": 1},
        )
    ).status_code == 200

    async def preview(category_id: uuid.UUID, scope: str, *, company: bool = False):
        task_id = await _upload(client)
        payload = {
            "target_scope": scope,
            "target_project_id": None if company else str(PROJECT_ALPHA),
            "confidentiality_level": "L2",
            "naming": {
                "category_id": str(category_id),
                "subject": "范围校验",
                "formed_on": "2026-08-10",
                "version": "V1",
                **({"applicable_to": "全体顾问"} if company else {}),
            },
        }
        return await client.post(
            f"/api/v1/ingest/{task_id}/naming-preview",
            headers=_hdr(USER_BOSS if company else USER_PROJECT_MANAGER),
            json=payload,
        )

    company_in_project = await preview(company_category_id, "project")
    project_in_company = await preview(project_category_id, "company", company=True)
    disabled_in_project = await preview(disabled_category_id, "project")
    for response in (company_in_project, project_in_company, disabled_in_project):
        assert response.status_code == 409
        assert response.json()["detail"]["denied_reason"] == "naming_category_unavailable"


async def test_category_directory_mapping_is_authoritative_and_fallback_is_explicit(client):
    mapped_id = uuid.uuid4()
    unmapped_id = uuid.uuid4()
    await _publish_categories(client, [(mapped_id, "交付件"), (unmapped_id, "未映射类别")])
    task_id = await _upload(client)

    base = {
        "target_scope": "project",
        "target_project_id": str(PROJECT_ALPHA),
        "confidentiality_level": "L2",
        "naming": {
            "category_id": str(mapped_id),
            "subject": "目录治理校验",
            "formed_on": "2026-08-17",
            "version": "V1",
            "directory_key": "project.guidance_process",
        },
    }
    mismatch = await client.post(
        f"/api/v1/ingest/{task_id}/naming-preview",
        headers=_hdr(USER_PROJECT_MANAGER),
        json=base,
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["denied_reason"] == "directory_category_mismatch"

    task_id = await _upload(client)
    base["naming"] = {
        **base["naming"],
        "category_id": str(unmapped_id),
    }
    base["naming"].pop("directory_key")
    missing = await client.post(
        f"/api/v1/ingest/{task_id}/naming-preview",
        headers=_hdr(USER_PROJECT_MANAGER),
        json=base,
    )
    assert missing.status_code == 422
    assert missing.json()["detail"]["denied_reason"] == "directory_required"

    base["naming"]["directory_key"] = "project.deliverables"
    unconfirmed = await client.post(
        f"/api/v1/ingest/{task_id}/naming-preview",
        headers=_hdr(USER_PROJECT_MANAGER),
        json=base,
    )
    assert unconfirmed.status_code == 422
    assert (
        unconfirmed.json()["detail"]["denied_reason"] == "directory_fallback_confirmation_required"
    )

    base["naming"]["directory_fallback_confirmed"] = True
    confirmed = await client.post(
        f"/api/v1/ingest/{task_id}/naming-preview",
        headers=_hdr(USER_PROJECT_MANAGER),
        json=base,
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["fields"]["directory_key"] == "project.deliverables"
    assert confirmed.json()["fields"]["directory_source"] == "manual_fallback"


async def test_project_aliases_are_normalized_and_validated(client):
    config = _config(uuid.uuid4(), client_aliases=["A"])
    too_short = await client.put(
        "/api/v1/admin/naming-rules/draft",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": 1, "config": config},
    )
    assert too_short.status_code == 422

    config = _config(uuid.uuid4(), client_aliases=["琥崧", " 琥崧 "])
    duplicate = await client.put(
        "/api/v1/admin/naming-rules/draft",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": 1, "config": config},
    )
    assert duplicate.status_code == 422


async def test_publish_activates_preview_and_confirmation_recomputes_name(client, db_session):
    category_id = uuid.uuid4()
    await _publish(client, category_id)
    center = await client.get("/api/v1/admin/naming-rules", headers=_hdr(USER_BOSS))
    assert center.json()["published"]["config"]["schema_version"] == 2
    assert center.json()["published"]["config"]["categories"][0]["asset_type"] == "deliverable"
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
            "confidentiality_level": "L2",
            "acknowledged_naming_warning_codes": _warning_codes(preview.json()),
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
    assert asset.asset_type == "deliverable"
    assert asset.visibility == "project_only"
    assert asset.ai_access_level == "A1"
    assert asset.lifecycle_phase_key is None
    assert version.naming_rule_version == 2
    assert version.naming_metadata["canonical_name"] == canonical


async def test_category_without_explicit_asset_type_cannot_be_published(client):
    category_id = uuid.uuid4()
    config = _config(category_id, category="尚未配置分类")
    config["categories"][0]["asset_type"] = None
    saved = await client.put(
        "/api/v1/admin/naming-rules/draft",
        headers=_hdr(USER_BOSS),
        json={
            "expected_base_version": 1,
            "config": config,
        },
    )
    assert saved.status_code == 200
    published = await client.post(
        "/api/v1/admin/naming-rules/publish",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": 1},
    )
    assert published.status_code == 422
    assert published.json()["detail"]["denied_reason"] == "naming_category_asset_type_required"


async def test_publish_conflict_is_stable(client):
    response = await client.post(
        "/api/v1/admin/naming-rules/publish",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": 999},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["denied_reason"] == "naming_rule_publish_conflict"


async def test_customer_name_is_a_soft_warning_and_can_be_retained(client, db_session):
    category_id = uuid.uuid4()
    config = _config(
        category_id,
        code="HS",
        client_aliases=["琥崧", "琥崧智能"],
        category="辅导过程",
    )
    saved = await client.put(
        "/api/v1/admin/naming-rules/draft",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": 1, "config": config},
    )
    assert saved.status_code == 200
    published = await client.post(
        "/api/v1/admin/naming-rules/publish",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": 1},
    )
    assert published.status_code == 200
    task_id = await _upload(client)
    naming = {
        "category_id": str(category_id),
        "subject": "琥崧智能2021年第1期辅导简报",
        "formed_on": "2021-03-07",
        "version": "V1",
    }

    preview = await client.post(
        f"/api/v1/ingest/{task_id}/naming-preview",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "confidentiality_level": "L3",
            "naming": naming,
        },
    )
    assert preview.status_code == 200
    expected = "【HS-2021-辅导过程】琥崧智能2021年第1期辅导简报_20210307_V1_L3.txt"
    assert preview.json()["canonical_name"] == expected
    assert preview.json()["fields"]["subject"] == "琥崧智能2021年第1期辅导简报"
    assert "project_subject_business_name" in _warning_codes(preview.json())

    confirmed = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "title": "伪造标题中的琥崧智能",
            "summary": "最终摘要",
            "tags": [],
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "target_zone": "material",
            "confidentiality_level": "L3",
            "acknowledged_naming_warning_codes": _warning_codes(preview.json()),
            "naming": naming,
        },
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["canonical_name"] == expected
    asset = await db_session.get(KnowledgeAsset, uuid.UUID(confirmed.json()["result_asset_id"]))
    assert asset.title == "琥崧智能2021年第1期辅导简报"
    assert "琥崧" in asset.canonical_name


async def test_non_pm_review_retains_acknowledged_business_subject(client, db_session):
    category_id = uuid.uuid4()
    config = _config(
        category_id,
        code="HS",
        client_aliases=["琥崧", "琥崧智能"],
        category="辅导过程",
    )
    saved = await client.put(
        "/api/v1/admin/naming-rules/draft",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": 1, "config": config},
    )
    assert saved.status_code == 200
    published = await client.post(
        "/api/v1/admin/naming-rules/publish",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": 1},
    )
    assert published.status_code == 200

    task_id = await _upload(client, USER_CONSULTANT)
    dirty_subject = "琥崧智能2021年第1期辅导简报"
    preview = await client.post(
        f"/api/v1/ingest/{task_id}/naming-preview",
        headers=_hdr(USER_CONSULTANT),
        json={
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "confidentiality_level": "L3",
            "naming": {
                "category_id": str(category_id),
                "subject": dirty_subject,
                "formed_on": "2021-03-07",
                "version": "V1",
            },
        },
    )
    assert preview.status_code == 200
    confirmed = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json={
            "title": f"伪造标题-{dirty_subject}",
            "summary": "待审核摘要",
            "tags": [],
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "target_zone": "material",
            "confidentiality_level": "L3",
            "acknowledged_naming_warning_codes": _warning_codes(preview.json()),
            "naming": {
                "category_id": str(category_id),
                "subject": dirty_subject,
                "formed_on": "2021-03-07",
                "version": "V1",
            },
        },
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "waiting_review"

    review_id = uuid.UUID(confirmed.json()["review_id"])
    review = await db_session.get(ReviewTask, review_id)
    assert review.confirmation_snapshot["title"] == dirty_subject
    assert review.confirmation_snapshot["naming"]["subject"] == dirty_subject

    approved = await client.post(
        f"/api/v1/reviews/{review_id}/approve",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={"review_comment": "命名已核对"},
    )
    assert approved.status_code == 200
    asset = await db_session.get(
        KnowledgeAsset,
        uuid.UUID(approved.json()["target_asset_id"]),
    )
    assert asset.title == dirty_subject
    assert "琥崧" in asset.canonical_name


async def test_business_name_warning_requires_explicit_acknowledgement(client):
    category_id = uuid.uuid4()
    saved = await client.put(
        "/api/v1/admin/naming-rules/draft",
        headers=_hdr(USER_BOSS),
        json={
            "expected_base_version": 1,
            "config": _config(category_id, client_aliases=["琥崧智能"]),
        },
    )
    assert saved.status_code == 200
    assert (
        await client.post(
            "/api/v1/admin/naming-rules/publish",
            headers=_hdr(USER_BOSS),
            json={"expected_base_version": 1},
        )
    ).status_code == 200
    task_id = await _upload(client)
    request = {
        "target_scope": "project",
        "target_project_id": str(PROJECT_ALPHA),
        "confidentiality_level": "L2",
        "naming": {
            "category_id": str(category_id),
            "subject": "阶段性琥崧智能辅导简报",
            "formed_on": "2021-03-07",
            "version": "V1",
        },
    }
    preview = await client.post(
        f"/api/v1/ingest/{task_id}/naming-preview",
        headers=_hdr(USER_PROJECT_MANAGER),
        json=request,
    )
    assert preview.status_code == 200
    assert preview.json()["canonical_name"] is not None
    assert "project_subject_business_name" in _warning_codes(preview.json())

    confirmed = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "title": "安全标题",
            "summary": "摘要",
            "tags": [],
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "target_zone": "material",
            "confidentiality_level": "L2",
            "naming": request["naming"],
        },
    )
    assert confirmed.status_code == 409
    assert confirmed.json()["detail"]["denied_reason"] == (
        "naming_warning_acknowledgement_required"
    )

    acknowledged = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "title": "安全标题",
            "summary": "摘要",
            "tags": [],
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "target_zone": "material",
            "confidentiality_level": "L2",
            "acknowledged_naming_warning_codes": _warning_codes(preview.json()),
            "naming": request["naming"],
        },
    )
    assert acknowledged.status_code == 200


async def test_disabled_or_absent_optional_alias_is_not_guessed(client):
    category_id = uuid.uuid4()
    saved = await client.put(
        "/api/v1/admin/naming-rules/draft",
        headers=_hdr(USER_BOSS),
        json={
            "expected_base_version": 1,
            "config": _config(
                category_id,
                client_aliases=["琥崧智能"],
                client_aliases_enabled=False,
            ),
        },
    )
    assert saved.status_code == 200
    assert (
        await client.post(
            "/api/v1/admin/naming-rules/publish",
            headers=_hdr(USER_BOSS),
            json={"expected_base_version": 1},
        )
    ).status_code == 200
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
                "subject": "琥崧智能辅导简报",
                "formed_on": "2021-03-07",
                "version": "V1",
            },
        },
    )
    assert preview.status_code == 200
    assert preview.json()["fields"]["subject"] == "琥崧智能辅导简报"

    display_name_preview = await client.post(
        f"/api/v1/ingest/{task_id}/naming-preview",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "confidentiality_level": "L2",
            "naming": {
                "category_id": str(category_id),
                "subject": "Alpha 项目2021年度复盘",
                "formed_on": "2021-03-07",
                "version": "V1",
            },
        },
    )
    assert display_name_preview.status_code == 200
    assert display_name_preview.json()["fields"]["subject"] == "Alpha 项目2021年度复盘"
    assert "project_subject_business_name" in _warning_codes(display_name_preview.json())


async def test_aliases_are_governed_without_business_api_or_audit_disclosure(client, db_session):
    category_id = uuid.uuid4()
    alias = "SECRET-CUSTOMER-ALIAS"
    saved = await client.put(
        "/api/v1/admin/naming-rules/draft",
        headers=_hdr(USER_BOSS),
        json={
            "expected_base_version": 1,
            "config": _config(category_id, client_aliases=[alias]),
        },
    )
    assert saved.status_code == 200
    assert (
        await client.post(
            "/api/v1/admin/naming-rules/publish",
            headers=_hdr(USER_BOSS),
            json={"expected_base_version": 1},
        )
    ).status_code == 200

    denied = await client.get("/api/v1/admin/naming-rules", headers=_hdr(USER_ADMIN_ONLY))
    assert denied.status_code == 403
    assert alias not in denied.text
    options = await client.get(
        "/api/v1/naming-options",
        headers=_hdr(USER_PROJECT_MANAGER),
        params={"scope": "project", "project_id": str(PROJECT_ALPHA)},
    )
    assert options.status_code == 200
    assert alias not in options.text
    events = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.action.in_(["naming_rule.draft_saved", "naming_rule.published"])
            )
        )
    ).scalars()
    assert alias not in json.dumps([event.after_snapshot for event in events], ensure_ascii=False)


async def test_non_member_cannot_use_project_preview_to_enumerate_aliases(client):
    category_id = uuid.uuid4()
    alias = "SECRET-CUSTOMER-ALIAS"
    saved = await client.put(
        "/api/v1/admin/naming-rules/draft",
        headers=_hdr(USER_BOSS),
        json={
            "expected_base_version": 1,
            "config": _config(category_id, client_aliases=[alias]),
        },
    )
    assert saved.status_code == 200
    assert (
        await client.post(
            "/api/v1/admin/naming-rules/publish",
            headers=_hdr(USER_BOSS),
            json={"expected_base_version": 1},
        )
    ).status_code == 200
    task_id = await _upload(client, USER_BOSS)

    response = await client.post(
        f"/api/v1/ingest/{task_id}/naming-preview",
        headers=_hdr(USER_BOSS),
        json={
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "confidentiality_level": "L2",
            "naming": {
                "category_id": str(category_id),
                "subject": f"{alias} 复盘",
                "formed_on": "2021-03-07",
                "version": "V1",
            },
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["denied_reason"] == "project_membership_required"
    assert alias not in json.dumps(response.json(), ensure_ascii=False)


async def test_batch_preview_and_confirm_keep_naming_failures_item_scoped(client, db_session):
    category_id = uuid.uuid4()
    await _publish(client, category_id)
    valid_task = await _upload(client)
    missing_date_task = await _upload(client)
    invalid_date_task = await _upload(client)
    exact_duplicate_task = await _upload(client)

    valid_naming = {
        "category_id": str(category_id),
        "subject": "批量项目复盘",
        "formed_on": "2026-08-02",
        "version": "V1",
    }
    preview = await client.post(
        "/api/v1/ingest/bulk-naming-preview",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "items": [
                {
                    "task_id": valid_task,
                    "confidentiality_level": "L2",
                    "naming": valid_naming,
                },
                {
                    "task_id": missing_date_task,
                    "confidentiality_level": "L2",
                    "naming": {
                        "category_id": str(category_id),
                        "subject": "缺少形成日期",
                        "version": "V1",
                    },
                },
            ],
        },
    )
    assert preview.status_code == 200
    by_id = {item["task_id"]: item for item in preview.json()["items"]}
    assert by_id[valid_task]["submittable"] is True
    assert by_id[valid_task]["canonical_name"].endswith("_20260802_V1_L2.txt")
    assert by_id[missing_date_task]["submittable"] is False
    assert by_id[missing_date_task]["error_code"] == "naming_formed_on_invalid"
    assert "storage" not in json.dumps(preview.json()).lower()

    def confirmation(
        title: str, naming: dict | None, warning_codes: list[str] | None = None
    ) -> dict:
        value = {
            "title": title,
            "summary": "批量确认摘要",
            "tags": [],
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "target_zone": "material",
            "confidentiality_level": "L2",
            "acknowledged_naming_warning_codes": warning_codes or [],
        }
        if naming is not None:
            value["naming"] = naming
        return value

    confirmed = await client.post(
        "/api/v1/ingest/bulk-confirm",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "items": [
                {
                    "task_id": valid_task,
                    "confirmation": confirmation(
                        "伪造标题", valid_naming, _warning_codes(by_id[valid_task])
                    ),
                },
                {
                    "task_id": missing_date_task,
                    "confirmation": confirmation("旧式无命名请求", None),
                },
                {
                    "task_id": invalid_date_task,
                    "confirmation": confirmation(
                        "错误形成日期",
                        {**valid_naming, "formed_on": "uploaded-today"},
                    ),
                },
            ],
        },
    )
    assert confirmed.status_code == 200
    results = {item["item_id"]: item for item in confirmed.json()["items"]}
    assert results[valid_task]["status"] == "succeeded"
    assert results[missing_date_task] == {
        "item_id": missing_date_task,
        "status": "skipped",
        "reason_code": "naming_fields_required",
        "message": "请补齐该资料的命名字段后重新核对",
    }
    assert results[invalid_date_task]["status"] == "skipped"
    assert results[invalid_date_task]["reason_code"] == "naming_formed_on_invalid"
    assert results[invalid_date_task]["message"] == "请填写有效的文件形成日期"
    asset = await db_session.scalar(
        select(KnowledgeAsset).where(KnowledgeAsset.title == "批量项目复盘")
    )
    assert asset is not None
    assert asset.canonical_name.endswith("_20260802_V1_L2.txt")

    duplicate_preview = await client.post(
        "/api/v1/ingest/bulk-naming-preview",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "items": [
                {
                    "task_id": exact_duplicate_task,
                    "confidentiality_level": "L2",
                    "naming": valid_naming,
                }
            ],
        },
    )
    duplicate_item = duplicate_preview.json()["items"][0]
    assert duplicate_item["submittable"] is True
    assert duplicate_item["error_code"] is None
    assert "exact" in {notice["kind"] for notice in duplicate_item["notices"]}
    assert duplicate_item["duplicate"]["duplicate_state"] == "exact_content"
    assert all(set(notice) == {"code", "kind", "message"} for notice in duplicate_item["notices"])

    independent = await client.post(
        f"/api/v1/ingest/{exact_duplicate_task}/duplicate-decision",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "action": "independent",
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
        },
    )
    assert independent.status_code == 200

    duplicate_confirm = await client.post(
        "/api/v1/ingest/bulk-confirm",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "items": [
                {
                    "task_id": exact_duplicate_task,
                    "confirmation": confirmation(
                        "重复资料", valid_naming, _warning_codes(duplicate_item)
                    ),
                }
            ],
        },
    )
    assert duplicate_confirm.status_code == 200
    assert duplicate_confirm.json()["items"][0]["status"] == "succeeded"
    assets = (
        (
            await db_session.execute(
                select(KnowledgeAsset).where(
                    KnowledgeAsset.canonical_name == duplicate_item["canonical_name"]
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(assets) == 2
    assert len({asset.id for asset in assets}) == 2
    audit_events = (
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == AuditAction.ingest_confirmed.value)
            )
        )
        .scalars()
        .all()
    )
    assert any(
        event.after_snapshot.get("naming_warnings_acknowledged") is True
        and "exact_duplicate" in event.after_snapshot.get("naming_warning_codes", [])
        for event in audit_events
    )


async def test_batch_preview_accepts_complete_frontend_project_contract(client):
    category_id = uuid.uuid4()
    await _publish(client, category_id)
    task_id = await _upload(client)

    response = await client.post(
        "/api/v1/ingest/bulk-naming-preview",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "items": [
                {
                    "task_id": task_id,
                    "confidentiality_level": "L2",
                    "naming": {
                        "category_id": str(category_id),
                        "subject": "财务部战略行动计划及年度工作计划",
                        "formed_on": "2021-01-16",
                        "version": "V1",
                    },
                }
            ],
        },
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["submittable"] is True
    assert item["canonical_name"].endswith("财务部战略行动计划及年度工作计划_20210116_V1_L2.txt")
    assert item["rule_version"] == 2
    assert item["notices"]
    assert all(notice["kind"] == "advisory" for notice in item["notices"])
    assert item["error_code"] is None


async def test_batch_preview_returns_field_specific_safe_validation_errors(client):
    category_id = uuid.uuid4()
    await _publish(client, category_id)
    task_ids = [await _upload(client) for _ in range(4)]
    base = {
        "category_id": str(category_id),
        "subject": "批量字段诊断",
        "formed_on": "2021-01-16",
        "version": "V1",
    }

    response = await client.post(
        "/api/v1/ingest/bulk-naming-preview",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "items": [
                {
                    "task_id": task_ids[0],
                    "confidentiality_level": "L2",
                    "naming": {**base, "formed_on": "not-a-date"},
                },
                {
                    "task_id": task_ids[1],
                    "confidentiality_level": "L2",
                    "naming": {**base, "version": "latest"},
                },
                {
                    "task_id": task_ids[2],
                    "confidentiality_level": "L2",
                    "naming": {**base, "category_id": str(uuid.uuid4())},
                },
                {
                    "task_id": task_ids[3],
                    "confidentiality_level": "L2",
                    "naming": {**base, "subject": ""},
                },
            ],
        },
    )

    assert response.status_code == 200
    codes = [item["error_code"] for item in response.json()["items"]]
    assert codes == [
        "naming_formed_on_invalid",
        "naming_version_invalid",
        "naming_category_unavailable",
        "naming_subject_invalid",
    ]
    body = json.dumps(response.json(), ensure_ascii=False).lower()
    assert "storage" not in body
    assert "trace" not in body


async def test_batch_preview_requires_company_applicable_to_per_item(client):
    project_category_id = uuid.uuid4()
    company_category_id = uuid.uuid4()
    saved = await client.put(
        "/api/v1/admin/naming-rules/draft",
        headers=_hdr(USER_BOSS),
        json={
            "expected_base_version": 1,
            "config": _config(
                project_category_id,
                company_category_id=company_category_id,
            ),
        },
    )
    assert saved.status_code == 200
    assert (
        await client.post(
            "/api/v1/admin/naming-rules/publish",
            headers=_hdr(USER_BOSS),
            json={"expected_base_version": 1},
        )
    ).status_code == 200
    task_id = await _upload(client, USER_BOSS)

    response = await client.post(
        "/api/v1/ingest/bulk-naming-preview",
        headers=_hdr(USER_BOSS),
        json={
            "target_scope": "company",
            "items": [
                {
                    "task_id": task_id,
                    "confidentiality_level": "L2",
                    "naming": {
                        "category_id": str(company_category_id),
                        "subject": "年度经营计划",
                        "formed_on": "2021-01-16",
                        "version": "V1",
                    },
                }
            ],
        },
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item.pop("duplicate")["duplicate_state"] == "none"
    assert item == {
        "task_id": task_id,
        "submittable": False,
        "canonical_name": None,
        "rule_version": None,
        "fields": None,
        "notices": [],
        "error_code": "naming_applicable_to_required",
        "message": "公司库资料必须填写适用对象",
        "suggested_version": "V1",
        "version_source": "default_needs_confirmation",
        "version_confidence": "low",
        "version_reason": "未能可靠判断版本，已使用规则默认值",
        "suggested_confidentiality_level": "L2",
        "confidentiality_source": "default_needs_confirmation",
        "confidentiality_confidence": "low",
        "confidentiality_reason": "AI 未能可靠判断内容密级，已使用规则默认值",
    }


async def test_batch_preview_authorizes_destination_before_task_probe(client):
    response = await client.post(
        "/api/v1/ingest/bulk-naming-preview",
        headers=_hdr(USER_BOSS),
        json={
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "items": [
                {
                    "task_id": str(uuid.uuid4()),
                    "confidentiality_level": "L2",
                    "naming": None,
                }
            ],
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["denied_reason"] == "project_membership_required"


async def test_category_classifier_uses_only_current_rule_candidates_and_not_filename(
    client, db_session
):
    foundation, delivery, review = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await _publish_categories(
        client,
        [(foundation, "项目基础信息"), (delivery, "交付成果"), (review, "项目复盘")],
    )
    upload = await client.post(
        "/api/v1/ingest/upload",
        headers=_hdr(USER_PROJECT_MANAGER),
        files={
            "file": (
                "【ALPHA-2026-交付成果】旧分类泄漏标记_20260803_V1_L2.txt",
                "项目复盘会议纪要，记录经验、问题与后续改进。".encode(),
                "text/plain",
            )
        },
    )
    task_id = upload.json()["ingest_task_id"]
    fake = _CategoryLLM(review)
    app.dependency_overrides[get_generation_llm_client] = lambda: fake

    response = await client.post(
        "/api/v1/ingest/bulk-category-classification",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "task_ids": [task_id],
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
        },
    )

    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["suggested_category_id"] == str(review)
    assert item["category_source"] == "ai_content"
    prompt = json.dumps(fake.messages, ensure_ascii=False)
    assert "项目基础信息" in prompt and "交付成果" in prompt and "项目复盘" in prompt
    assert "旧分类泄漏标记" not in prompt
    ai = await db_session.scalar(
        select(IngestTaskAiResult).where(IngestTaskAiResult.ingest_task_id == uuid.UUID(task_id))
    )
    assert ai.naming_parsed_fields["category_suggestion"]["suggested_category_id"] == str(review)


async def test_category_classifier_invalid_id_fails_to_manual(client):
    first, second = uuid.uuid4(), uuid.uuid4()
    await _publish_categories(client, [(first, "辅导过程"), (second, "关键资料")])
    task_id = await _upload(client)
    fake = _CategoryLLM(uuid.uuid4(), confidence="high")
    app.dependency_overrides[get_generation_llm_client] = lambda: fake

    response = await client.post(
        "/api/v1/ingest/bulk-category-classification",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "task_ids": [task_id],
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
        },
    )
    item = response.json()["items"][0]
    assert item["suggested_category_id"] is None
    assert item["category_source"] == "needs_manual"
    assert item["category_confidence"] == "low"

    low_fake = _CategoryLLM(first, confidence="low")
    app.dependency_overrides[get_generation_llm_client] = lambda: low_fake
    low = await client.post(
        "/api/v1/ingest/bulk-category-classification",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "task_ids": [task_id],
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "retry": True,
        },
    )
    assert low.json()["items"][0]["suggested_category_id"] is None
    assert low.json()["items"][0]["category_source"] == "needs_manual"


async def test_manual_batch_category_confirmation_overrides_stored_ai_suggestion(
    client, db_session
):
    ai_category, manual_category = uuid.uuid4(), uuid.uuid4()
    await _publish_categories(
        client,
        [(ai_category, "项目复盘"), (manual_category, "交付成果")],
    )
    task_id = await _upload(client)
    ai = await db_session.scalar(
        select(IngestTaskAiResult).where(IngestTaskAiResult.ingest_task_id == uuid.UUID(task_id))
    )
    ai.naming_parsed_fields = {
        **(ai.naming_parsed_fields or {}),
        "category_suggestion": {
            "suggested_category_id": str(ai_category),
            "category_source": "ai_content",
            "category_confidence": "high",
            "category_reason": "旧 AI 建议",
            "candidate_rule_revision": 2,
            "status": "classified",
        },
    }
    await db_session.commit()

    naming = {
        "category_id": str(manual_category),
        "subject": "人工批量类别覆盖",
        "formed_on": "2026-08-14",
        "version": "V1",
    }
    preview = await client.post(
        f"/api/v1/ingest/{task_id}/naming-preview",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "confidentiality_level": "L2",
            "naming": naming,
        },
    )
    assert preview.status_code == 200, preview.text
    confirmed = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "title": "人工批量类别覆盖",
            "summary": "人工确认摘要",
            "tags": [],
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "target_zone": "material",
            "confidentiality_level": "L2",
            "acknowledged_naming_warning_codes": _warning_codes(preview.json()),
            "naming": naming,
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert "交付成果" in confirmed.json()["canonical_name"]
    assert "项目复盘" not in confirmed.json()["canonical_name"]


async def test_category_classifier_batches_twenty_safe_drafts_without_extracted_text(client):
    first, second = uuid.uuid4(), uuid.uuid4()
    await _publish_categories(client, [(first, "辅导过程"), (second, "项目复盘")])
    task_ids = [await _upload(client) for _ in range(13)]
    fake = _BatchCategoryLLM(second)
    app.dependency_overrides[get_generation_llm_client] = lambda: fake

    response = await client.post(
        "/api/v1/ingest/bulk-category-classification",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "task_ids": task_ids,
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
        },
    )

    assert response.status_code == 200, response.text
    assert len(fake.messages) == 1
    assert [len(json.loads(message[1]["content"])["documents"]) for message in fake.messages] == [
        13
    ]
    prompt = json.dumps(fake.messages, ensure_ascii=False)
    assert "extracted_text" not in prompt
    assert "document_text" not in prompt
    assert {item["suggested_category_id"] for item in response.json()["items"]} == {str(second)}


async def test_upload_then_choose_project_reuses_first_generation_category(client):
    first, second = uuid.uuid4(), uuid.uuid4()
    await _publish_categories(client, [(first, "辅导过程"), (second, "项目复盘")])
    fake = _CombinedGenerationCategoryLLM(second)
    app.dependency_overrides[get_generation_llm_client] = lambda: fake

    task_id = await _upload(client)
    assert fake.calls == 1
    prompt = fake.messages[0][1]["content"]
    assert '"target_scope": "pending_selection"' in prompt
    assert '"scope": "project"' in prompt

    response = await client.post(
        "/api/v1/ingest/bulk-category-classification",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "task_ids": [task_id],
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["suggested_category_id"] == str(second)
    assert fake.calls == 1


async def test_category_classifier_splits_complete_json_before_input_budget(client, db_session):
    first, second = uuid.uuid4(), uuid.uuid4()
    await _publish_categories(client, [(first, "辅导过程"), (second, "项目复盘")])
    task_ids = [await _upload(client) for _ in range(20)]
    rows = (
        (
            await db_session.execute(
                select(IngestTaskAiResult).where(
                    IngestTaskAiResult.ingest_task_id.in_([uuid.UUID(item) for item in task_ids])
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.suggested_one_liner = "一" * 240
        row.suggested_summary = "摘" * 1_000
        row.suggested_key_points = ["点" * 100] * 6
    await db_session.commit()
    fake = _BatchCategoryLLM(second)
    app.dependency_overrides[get_generation_llm_client] = lambda: fake

    response = await client.post(
        "/api/v1/ingest/bulk-category-classification",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "task_ids": task_ids,
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
        },
    )

    assert response.status_code == 200, response.text
    assert len(fake.messages) > 1
    documents = []
    for messages in fake.messages:
        assert sum(len(message["content"]) for message in messages) <= 20_000
        documents.extend(json.loads(messages[1]["content"])["documents"])
    assert len(documents) == 20


async def test_category_partial_result_retries_only_the_missing_item(client):
    first, second = uuid.uuid4(), uuid.uuid4()
    await _publish_categories(client, [(first, "辅导过程"), (second, "项目复盘")])
    task_ids = [await _upload(client) for _ in range(20)]
    fake = _PartialBatchCategoryLLM(second)
    app.dependency_overrides[get_generation_llm_client] = lambda: fake

    first_response = await client.post(
        "/api/v1/ingest/bulk-category-classification",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "task_ids": task_ids,
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
        },
    )
    failed = [item for item in first_response.json()["items"] if item["status"] == "failed"]
    assert len(failed) == 1
    retry = await client.post(
        "/api/v1/ingest/bulk-category-classification",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "task_ids": [failed[0]["task_id"]],
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "retry": True,
        },
    )

    assert retry.json()["items"][0]["status"] == "classified"
    assert [len(json.loads(message[1]["content"])["documents"]) for message in fake.messages] == [
        20,
        1,
    ]


async def test_category_classifier_non_object_json_fails_each_item_safely(client):
    first, second = uuid.uuid4(), uuid.uuid4()
    await _publish_categories(client, [(first, "辅导过程"), (second, "关键资料")])
    task_id = await _upload(client)

    for raw in ("[]", '"文本"', "42"):
        app.dependency_overrides[get_generation_llm_client] = lambda raw=raw: _RawCategoryLLM(raw)
        response = await client.post(
            "/api/v1/ingest/bulk-category-classification",
            headers=_hdr(USER_PROJECT_MANAGER),
            json={
                "task_ids": [task_id],
                "target_scope": "project",
                "target_project_id": str(PROJECT_ALPHA),
                "retry": True,
            },
        )

        assert response.status_code == 200, response.text
        item = response.json()["items"][0]
        assert item["suggested_category_id"] is None
        assert item["category_source"] == "needs_manual"
        assert item["status"] == "failed"
        assert item["retryable"] is True


async def test_only_category_is_rule_source_without_llm_call(client):
    only = uuid.uuid4()
    await _publish_categories(client, [(only, "项目基础信息")])
    task_id = await _upload(client)
    fake = _CategoryLLM(None)
    app.dependency_overrides[get_generation_llm_client] = lambda: fake

    response = await client.post(
        "/api/v1/ingest/bulk-category-classification",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "task_ids": [task_id],
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
        },
    )
    item = response.json()["items"][0]
    assert item["suggested_category_id"] == str(only)
    assert item["category_source"] == "rule_only_option"
    assert fake.messages == []


async def test_manual_category_survives_retry(client):
    first, second = uuid.uuid4(), uuid.uuid4()
    await _publish_categories(client, [(first, "辅导过程"), (second, "项目复盘")])
    task_id = await _upload(client)
    selected = await client.put(
        f"/api/v1/ingest/{task_id}/category-selection",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "category_id": str(first),
        },
    )
    assert selected.status_code == 200
    fake = _CategoryLLM(second)
    app.dependency_overrides[get_generation_llm_client] = lambda: fake
    retried = await client.post(
        "/api/v1/ingest/bulk-category-classification",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "task_ids": [task_id],
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "retry": True,
        },
    )
    item = retried.json()["items"][0]
    assert item["suggested_category_id"] == str(first)
    assert item["category_source"] == "manual"
    assert fake.messages == []


async def test_stale_manual_category_requires_reselection_without_llm(client, db_session):
    first, second = uuid.uuid4(), uuid.uuid4()
    await _publish_categories(client, [(first, "辅导过程"), (second, "项目复盘")])
    task_id = await _upload(client)
    selected = await client.put(
        f"/api/v1/ingest/{task_id}/category-selection",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "category_id": str(first),
        },
    )
    initial_revision = selected.json()["candidate_rule_revision"]

    replacement, other = uuid.uuid4(), uuid.uuid4()
    config = _config(replacement, category="关键资料")
    config["categories"].append(
        {
            "id": str(other),
            "scope": "project",
            "primary": "项目资料",
            "secondary": "项目基础信息",
            "prefix": "项目资料-项目基础信息",
            "default_confidentiality": "L2",
            "asset_type": "deliverable",
            "enabled": True,
            "sort_order": 20,
        }
    )
    saved = await client.put(
        "/api/v1/admin/naming-rules/draft",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": initial_revision, "config": config},
    )
    assert saved.status_code == 200, saved.text
    published = await client.post(
        "/api/v1/admin/naming-rules/publish",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": initial_revision},
    )
    assert published.status_code == 200, published.text
    fake = _CategoryLLM(replacement)
    app.dependency_overrides[get_generation_llm_client] = lambda: fake

    refreshed = await client.post(
        "/api/v1/ingest/bulk-category-classification",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "task_ids": [task_id],
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "retry": True,
        },
    )

    assert refreshed.status_code == 200, refreshed.text
    item = refreshed.json()["items"][0]
    assert item["suggested_category_id"] is None
    assert item["category_source"] == "needs_manual"
    assert item["status"] == "needs_manual"
    assert fake.messages == []
    ai = await db_session.scalar(
        select(IngestTaskAiResult)
        .where(IngestTaskAiResult.ingest_task_id == uuid.UUID(task_id))
        .execution_options(populate_existing=True)
    )
    stored = ai.naming_parsed_fields["category_suggestion"]
    assert stored["suggested_category_id"] == str(first)
    assert stored["category_source"] == "manual"


async def test_manual_project_category_is_not_returned_for_company_target(client):
    project_category, company_category = uuid.uuid4(), uuid.uuid4()
    config = _config(project_category, company_category_id=company_category)
    saved = await client.put(
        "/api/v1/admin/naming-rules/draft",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": 1, "config": config},
    )
    assert saved.status_code == 200, saved.text
    published = await client.post(
        "/api/v1/admin/naming-rules/publish",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": 1},
    )
    assert published.status_code == 200, published.text
    task_id = await _upload(client)
    selected = await client.put(
        f"/api/v1/ingest/{task_id}/category-selection",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "category_id": str(project_category),
        },
    )
    assert selected.status_code == 200, selected.text
    fake = _CategoryLLM(company_category)
    app.dependency_overrides[get_generation_llm_client] = lambda: fake

    switched = await client.post(
        "/api/v1/ingest/bulk-category-classification",
        headers=_hdr(USER_BOSS),
        json={
            "task_ids": [task_id],
            "target_scope": "company",
            "target_project_id": None,
            "retry": True,
        },
    )

    assert switched.status_code == 200, switched.text
    item = switched.json()["items"][0]
    assert item["suggested_category_id"] is None
    assert item["category_source"] == "needs_manual"
    assert fake.messages == []


async def test_manual_category_wins_when_concurrent_retry_finishes_late(client, db_session):
    first, second = uuid.uuid4(), uuid.uuid4()
    await _publish_categories(client, [(first, "辅导过程"), (second, "项目复盘")])
    task_id = await _upload(client)
    fake = _BlockingCategoryLLM(second)
    app.dependency_overrides[get_generation_llm_client] = lambda: fake

    retry_request = asyncio.create_task(
        client.post(
            "/api/v1/ingest/bulk-category-classification",
            headers=_hdr(USER_PROJECT_MANAGER),
            json={
                "task_ids": [task_id],
                "target_scope": "project",
                "target_project_id": str(PROJECT_ALPHA),
                "retry": True,
            },
        )
    )
    await asyncio.wait_for(fake.started.wait(), timeout=1)

    selected = await client.put(
        f"/api/v1/ingest/{task_id}/category-selection",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "category_id": str(first),
        },
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["category_source"] == "manual"

    fake.release.set()
    retried = await asyncio.wait_for(retry_request, timeout=2)
    assert retried.status_code == 200, retried.text
    item = retried.json()["items"][0]
    assert item["suggested_category_id"] == str(first)
    assert item["category_source"] == "manual"

    ai = await db_session.scalar(
        select(IngestTaskAiResult)
        .where(IngestTaskAiResult.ingest_task_id == uuid.UUID(task_id))
        .execution_options(populate_existing=True)
    )
    stored = ai.naming_parsed_fields["category_suggestion"]
    assert stored["suggested_category_id"] == str(first)
    assert stored["category_source"] == "manual"


async def test_published_rule_change_invalidates_old_ai_category(client):
    first, second = uuid.uuid4(), uuid.uuid4()
    await _publish_categories(client, [(first, "辅导过程"), (second, "项目复盘")])
    task_id = await _upload(client)
    initial_fake = _CategoryLLM(first)
    app.dependency_overrides[get_generation_llm_client] = lambda: initial_fake
    initial = await client.post(
        "/api/v1/ingest/bulk-category-classification",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "task_ids": [task_id],
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
        },
    )
    initial_revision = initial.json()["candidate_rule_revision"]

    replacement, other = uuid.uuid4(), uuid.uuid4()
    config = _config(replacement, category="关键资料")
    config["categories"].append(
        {
            "id": str(other),
            "scope": "project",
            "primary": "项目资料",
            "secondary": "项目基础信息",
            "prefix": "项目资料-项目基础信息",
            "default_confidentiality": "L2",
            "asset_type": "deliverable",
            "enabled": True,
            "sort_order": 20,
        }
    )
    saved = await client.put(
        "/api/v1/admin/naming-rules/draft",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": initial_revision, "config": config},
    )
    assert saved.status_code == 200, saved.text
    published = await client.post(
        "/api/v1/admin/naming-rules/publish",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": initial_revision},
    )
    assert published.status_code == 200, published.text
    replacement_fake = _CategoryLLM(replacement)
    app.dependency_overrides[get_generation_llm_client] = lambda: replacement_fake

    refreshed = await client.post(
        "/api/v1/ingest/bulk-category-classification",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "task_ids": [task_id],
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
        },
    )
    item = refreshed.json()["items"][0]
    assert refreshed.json()["candidate_rule_revision"] != initial_revision
    assert item["suggested_category_id"] == str(replacement)
    assert len(replacement_fake.messages) == 1


async def test_empty_category_rules_never_fall_back_to_deliverable(client):
    config = _config(uuid.uuid4())
    config["categories"] = []
    saved = await client.put(
        "/api/v1/admin/naming-rules/draft",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": 1, "config": config},
    )
    assert saved.status_code == 200
    published = await client.post(
        "/api/v1/admin/naming-rules/publish",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": 1},
    )
    assert published.status_code == 200
    task_id = await _upload(client)
    response = await client.post(
        "/api/v1/ingest/bulk-category-classification",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "task_ids": [task_id],
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
        },
    )
    assert response.json()["candidate_count"] == 0
    item = response.json()["items"][0]
    assert item["suggested_category_id"] is None
    assert item["category_source"] == "needs_manual"
    assert "未配置" in item["category_reason"]


async def test_unconfigured_classifier_is_retryable_manual_not_default(client):
    first, second = uuid.uuid4(), uuid.uuid4()
    await _publish_categories(client, [(first, "辅导过程"), (second, "项目复盘")])
    task_id = await _upload(client)
    app.dependency_overrides[get_generation_llm_client] = lambda: NullLLMClient()
    response = await client.post(
        "/api/v1/ingest/bulk-category-classification",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "task_ids": [task_id],
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
        },
    )
    item = response.json()["items"][0]
    assert item["suggested_category_id"] is None
    assert item["category_source"] == "needs_manual"
    assert item["status"] == "failed"
    assert item["retryable"] is True

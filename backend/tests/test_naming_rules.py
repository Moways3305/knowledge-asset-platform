"""Governed naming rules and server-authoritative confirmation previews."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select

from app.models.audit import AuditEvent
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.review import ReviewTask
from app.seed.dev_seed import (
    PROJECT_ALPHA,
    PROJECT_BETA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_PROJECT_MANAGER,
)


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
        "schema_version": 1,
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


async def test_unknown_category_asset_type_mapping_fails_closed(client):
    category_id = uuid.uuid4()
    saved = await client.put(
        "/api/v1/admin/naming-rules/draft",
        headers=_hdr(USER_BOSS),
        json={
            "expected_base_version": 1,
            "config": _config(category_id, category="尚未配置分类"),
        },
    )
    assert saved.status_code == 200
    published = await client.post(
        "/api/v1/admin/naming-rules/publish",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": 1},
    )
    assert published.status_code == 200
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
                "subject": "待分类主题",
                "formed_on": "2026-08-03",
                "version": "V1",
            },
        },
    )
    assert preview.status_code == 409
    assert preview.json()["detail"]["denied_reason"] == "naming_asset_type_mapping_missing"


async def test_publish_conflict_is_stable(client):
    response = await client.post(
        "/api/v1/admin/naming-rules/publish",
        headers=_hdr(USER_BOSS),
        json={"expected_base_version": 999},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["denied_reason"] == "naming_rule_publish_conflict"


async def test_husong_alias_is_removed_and_confirm_uses_authoritative_subject(client, db_session):
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
    expected = "【HS-2021-辅导过程】2021年第1期辅导简报_20210307_V1_L3.txt"
    assert preview.json()["canonical_name"] == expected
    assert preview.json()["fields"]["subject"] == "2021年第1期辅导简报"

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
            "naming": naming,
        },
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["canonical_name"] == expected
    asset = await db_session.get(KnowledgeAsset, uuid.UUID(confirmed.json()["result_asset_id"]))
    assert asset.title == "2021年第1期辅导简报"
    assert "琥崧" not in asset.canonical_name


async def test_non_pm_review_snapshot_and_approval_use_authoritative_subject(client, db_session):
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
    clean_subject = "2021年第1期辅导简报"
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
    assert review.confirmation_snapshot["title"] == clean_subject
    assert review.confirmation_snapshot["naming"]["subject"] == clean_subject

    # Simulate a review snapshot created before this fix. Approval must apply
    # current server policy again instead of trusting its stored title/subject.
    legacy_snapshot = dict(review.confirmation_snapshot)
    legacy_snapshot["title"] = dirty_subject
    legacy_snapshot["naming"] = {**legacy_snapshot["naming"], "subject": dirty_subject}
    review.confirmation_snapshot = legacy_snapshot
    await db_session.commit()

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
    assert asset.title == clean_subject
    assert "琥崧" not in asset.canonical_name


async def test_ambiguous_alias_match_blocks_preview_and_direct_confirmation(client):
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
    assert preview.status_code == 422
    assert preview.json()["detail"] == {
        "denied_reason": "project_subject_customer_name_detected",
        "message": "主题可能包含客户名称，请修改后继续",
    }
    assert "琥崧" not in json.dumps(preview.json(), ensure_ascii=False)

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
    assert confirmed.status_code == 422
    assert confirmed.json()["detail"]["denied_reason"] == ("project_subject_customer_name_detected")


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
    assert display_name_preview.json()["fields"]["subject"] == "2021年度复盘"


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

    def confirmation(title: str, naming: dict | None) -> dict:
        value = {
            "title": title,
            "summary": "批量确认摘要",
            "tags": [],
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "target_zone": "material",
            "confidentiality_level": "L2",
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
                {"task_id": valid_task, "confirmation": confirmation("伪造标题", valid_naming)},
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
    assert duplicate_item["submittable"] is False
    assert duplicate_item["error_code"] == "naming_exact_duplicate"
    assert {notice["kind"] for notice in duplicate_item["notices"]} == {"exact", "suspected"}
    assert all(set(notice) == {"kind", "message"} for notice in duplicate_item["notices"])

    duplicate_confirm = await client.post(
        "/api/v1/ingest/bulk-confirm",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "items": [
                {
                    "task_id": exact_duplicate_task,
                    "confirmation": confirmation("重复资料", valid_naming),
                }
            ],
        },
    )
    assert duplicate_confirm.status_code == 200
    assert duplicate_confirm.json()["items"][0]["reason_code"] == "naming_exact_duplicate"


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
    assert item["notices"] == []
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
    assert response.json()["items"][0] == {
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

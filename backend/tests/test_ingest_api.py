"""入库流水线 API 测试（IMPLEMENT-05，Path B 最小闭环）。"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

from app.models.audit import AuditEvent
from app.models.ingest import IngestTask, IngestTaskAiResult
from app.models.knowledge import KnowledgeAssetVersion
from app.models.weknora import WeknoraKbMapping
from app.schemas.enums import AuditAction
from app.seed.dev_seed import (
    PROJECT_ALPHA,
    PROJECT_BETA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_PROJECT_MANAGER,
)
from app.services import ingest as ingest_service
from app.services import ingest_confirmation
from app.services.storage import LocalFileStorage, StorageError

UPLOAD = "/api/v1/ingest/upload"
KN = "/api/v1/knowledge"
MY = "/api/v1/my/knowledge"


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


_TXT_BYTES = (
    "零售数字化转型方案\n"
    "第一章 背景\n"
    "本文介绍零售企业数字化转型的五维度成熟度评估方法论与落地路径。"
).encode()

_MD_BYTES = (
    "# 项目复盘\n\n"
    "- 客户访谈纪要\n"
    "- 后续行动\n\n"
    "| 主题 | 结论 |\n"
    "| --- | --- |\n"
    "| 组织 | 需要统一节奏 |\n"
).encode()


async def _create_task(client, user_id, file_name="retail-strategy-v2.txt"):
    # Path B 现为真实文件上传 + 真实文本抽取；发送可抽取的真实文本字节。
    resp = await client.post(
        UPLOAD,
        headers=_hdr(user_id),
        files={"file": (file_name, _TXT_BYTES, "text/plain")},
    )
    return resp


def _confirm_payload(**over):
    base = {
        "title": "入库确认资产",
        "summary": "确认后的摘要内容",
        "tags": ["标签A", "标签B"],
        "target_scope": "personal",
        "target_zone": "material",
        "confidentiality_level": "L2",
    }
    base.update(over)
    return base


async def test_business_user_create_upload_no_internal_fields(client):
    """业务用户创建 upload 成功，响应不含内部字段 / 真实 URL。"""
    resp = await _create_task(client, USER_CONSULTANT)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ingest_task_id"]
    assert body["status"] == "pending_confirmation"
    assert body["upload_url"] is None
    assert "source_file_ref" not in resp.text
    assert "storage_ref" not in resp.text


async def test_admin_create_upload_403(client):
    """纯 admin 创建 upload 返回 403 + admin_business_permission_denied。"""
    resp = await _create_task(client, USER_ADMIN_ONLY)
    assert resp.status_code == 403
    assert resp.json()["detail"]["denied_reason"] == "admin_business_permission_denied"


async def test_ai_result_no_internal_fields(client):
    """获取 AI 建议不泄露内部字段（source_file_ref / storage_ref）。"""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    resp = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    assert resp.status_code == 200
    assert resp.json()["suggested_title"]  # 创建人可见完整建议
    assert "source_file_ref" not in resp.text
    assert "storage_ref" not in resp.text
    body = resp.json()
    assert body["suggestion_generation_status"] in {
        "generated",
        "needs_correction",
        "needs_manual_completion",
    }
    assert body["suggestion_generation_reason"]
    assert "%" not in body["suggestion_generation_reason"]


async def test_legacy_naming_advice_defaults_are_safe_and_stable(client, db_session):
    """Rows created before provenance columns never masquerade as AI advice."""
    task_id = uuid.UUID((await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"])
    ai = (
        await db_session.execute(
            select(IngestTaskAiResult).where(IngestTaskAiResult.ingest_task_id == task_id)
        )
    ).scalar_one()
    ai.suggested_version = None
    ai.version_source = None
    ai.version_confidence = None
    ai.version_reason = None
    # Old rows may contain a level parsed from the filename. It is not AI content advice.
    ai.suggested_confidentiality_level = "L5"
    ai.confidentiality_source = None
    ai.confidentiality_confidence = None
    ai.confidentiality_reason = None
    await db_session.commit()

    detail = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    first_pending = await client.get("/api/v1/ingest/pending", headers=_hdr(USER_CONSULTANT))
    second_pending = await client.get("/api/v1/ingest/pending", headers=_hdr(USER_CONSULTANT))
    first_item = next(item for item in first_pending.json()["items"] if item["id"] == str(task_id))
    second_item = next(
        item for item in second_pending.json()["items"] if item["id"] == str(task_id)
    )

    for payload in (detail.json(), first_item, second_item):
        assert payload["suggested_version"] == "V1"
        assert payload["version_source"] == "default_needs_confirmation"
        assert payload["version_confidence"] == "low"
        assert payload["suggested_confidentiality_level"] == "L2"
        assert payload["confidentiality_source"] == "default_needs_confirmation"
        assert payload["confidentiality_confidence"] == "low"
        assert "L5" not in payload["confidentiality_reason"]


async def test_source_locked_destination_cannot_be_overridden(client, db_session):
    task_id = (await _create_task(client, USER_PROJECT_MANAGER)).json()["ingest_task_id"]
    await db_session.execute(
        update(IngestTask)
        .where(IngestTask.id == uuid.UUID(task_id))
        .values(target_scope="personal", target_project_id=None)
    )
    await db_session.commit()

    response = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_PROJECT_MANAGER),
        json=_confirm_payload(
            target_scope="project",
            target_project_id=str(PROJECT_ALPHA),
        ),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["denied_reason"] == "ingest_target_locked"


async def test_bulk_confirm_has_one_explicit_target_and_partial_terminal_result(client, db_session):
    first = (await _create_task(client, USER_CONSULTANT, "first.txt")).json()["ingest_task_id"]
    second = (await _create_task(client, USER_CONSULTANT, "second.txt")).json()["ingest_task_id"]
    payload = _confirm_payload(target_scope="personal")
    confirmed = await client.post(
        f"/api/v1/ingest/{first}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=payload,
    )
    assert confirmed.status_code == 200

    missing_target = await client.post(
        "/api/v1/ingest/bulk-confirm",
        headers=_hdr(USER_CONSULTANT),
        json={"items": [{"task_id": second, "confirmation": payload}]},
    )
    assert missing_target.status_code == 422

    client_operation_id = uuid.uuid4()
    response = await client.post(
        "/api/v1/ingest/bulk-confirm",
        headers=_hdr(USER_CONSULTANT),
        json={
            "target_scope": "personal",
            "target_project_id": None,
            "client_operation_id": str(client_operation_id),
            "request_index": 2,
            "request_count": 4,
            "total_submitted": 700,
            "items": [
                {"task_id": first, "confirmation": payload},
                {"task_id": second, "confirmation": payload},
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed_with_errors"
    assert body["submitted"] == 2
    assert body["succeeded"] == 1
    assert body["skipped"] == 1
    assert body["failed"] == 0
    results_by_task = {item["item_id"]: item for item in body["items"]}
    assert "result_asset_id" not in results_by_task[first]
    assert results_by_task[second]["result_asset_id"]
    audit = (
        (
            await db_session.execute(
                select(AuditEvent)
                .where(AuditEvent.action == "ingest.bulk_confirmed")
                .order_by(AuditEvent.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    assert audit is not None
    assert audit.extra["client_operation_id"] == str(client_operation_id)
    assert audit.extra["request_index"] == 2
    assert audit.extra["request_count"] == 4
    assert audit.extra["logical_submitted"] == 700
    assert "token" not in str(audit.extra).lower()
    assert "source_file" not in str(audit.extra).lower()
    assert "result_asset_id" not in audit.extra


async def test_confirm_index_unexpected_failure_keeps_asset(client, db_session, monkeypatch):
    """确认落库后索引抛未预期异常：资产保留、返回 index_failed（而非失败），版本可运维重试。"""

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("unexpected index failure")

    monkeypatch.setattr("app.services.ingest.weknora_enabled", lambda: True)
    monkeypatch.setattr("app.services.ingest_indexing.index_confirmed_asset", _boom)

    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    resp = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_confirm_payload(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["result_asset_id"]
    assert body["status"] == "completed"
    assert body["index_status"] == "index_failed"

    version = (
        await db_session.execute(
            select(KnowledgeAssetVersion).where(
                KnowledgeAssetVersion.asset_id == uuid.UUID(body["result_asset_id"])
            )
        )
    ).scalar_one()
    assert version.index_status == "index_failed"
    assert version.index_error_code == "index_unexpected_error"

    audit = (
        (
            await db_session.execute(
                select(AuditEvent)
                .where(AuditEvent.action == AuditAction.ingest_index_failed.value)
                .order_by(AuditEvent.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    assert audit is not None
    assert audit.extra["failure_stage"] == "weknora_index_unexpected"
    assert audit.extra["error_code"] == "index_unexpected_error"


async def test_bulk_confirm_index_unexpected_failure_reports_succeeded(
    client, db_session, monkeypatch
):
    """批量确认：索引未预期异常不把已确认项误报为 failed，仍回传 result_asset_id。"""

    async def _boom(*_args, **_kwargs):
        raise RuntimeError("unexpected index failure")

    monkeypatch.setattr("app.services.ingest.weknora_enabled", lambda: True)
    monkeypatch.setattr("app.services.ingest_indexing.index_confirmed_asset", _boom)

    first = (await _create_task(client, USER_CONSULTANT, "first.txt")).json()["ingest_task_id"]
    second = (await _create_task(client, USER_CONSULTANT, "second.txt")).json()["ingest_task_id"]
    payload = _confirm_payload(target_scope="personal")
    resp = await client.post(
        "/api/v1/ingest/bulk-confirm",
        headers=_hdr(USER_CONSULTANT),
        json={
            "target_scope": "personal",
            "target_project_id": None,
            "items": [
                {"task_id": first, "confirmation": payload},
                {"task_id": second, "confirmation": payload},
            ],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["succeeded"] == 2
    assert body["failed"] == 0
    for item in body["items"]:
        assert item["status"] == "succeeded"
        assert item["result_asset_id"]


async def test_confirmed_task_result_helper_resolves_persisted_asset(client, db_session):
    """残差防御辅助函数：已确认任务返回 succeeded + asset id，未确认返回 None。"""
    from app.api.ingest import _confirmed_task_result

    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    assert await _confirmed_task_result(db_session, uuid.UUID(task_id)) is None

    resp = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_confirm_payload(),
    )
    assert resp.status_code == 200
    result = await _confirmed_task_result(db_session, uuid.UUID(task_id))
    assert result is not None
    assert result.status == "succeeded"
    assert result.result_asset_id == uuid.UUID(resp.json()["result_asset_id"])


async def test_ai_result_admin_trimmed(client):
    """admin 看 AI 建议只得运营元数据，不返回业务建议正文。"""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    resp = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_ADMIN_ONLY))
    assert resp.status_code == 200
    body = resp.json()
    assert body["suggested_title"] is None
    assert body["suggested_summary"] is None
    assert body["confidence"] is not None  # 运营元数据仍可见


async def test_confirm_personal_then_visible_in_my_knowledge(client):
    """确认 personal 入库后，/my/knowledge 可看到新资产。"""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    resp = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_confirm_payload(title="我的入库个人资产", target_scope="personal"),
    )
    assert resp.status_code == 200
    asset_id = resp.json()["result_asset_id"]
    my = (await client.get(MY, headers=_hdr(USER_CONSULTANT))).json()
    assert any(i["id"] == asset_id for i in my["items"])


async def test_confirmation_extension_only_receives_server_validated_target(client, monkeypatch):
    """The naming extension boundary is unreachable until target checks pass."""
    contexts: list[ingest_confirmation.ValidatedConfirmationContext] = []

    async def capture_context(
        context: ingest_confirmation.ValidatedConfirmationContext,
    ) -> ingest_confirmation.ValidatedConfirmationContext:
        contexts.append(context)
        return context

    monkeypatch.setattr(ingest_confirmation, "apply_confirmation_extensions", capture_context)

    rejected_task = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    rejected = await client.post(
        f"/api/v1/ingest/{rejected_task}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_confirm_payload(
            target_scope="project",
            target_project_id=str(PROJECT_BETA),
        ),
    )
    assert rejected.status_code == 403
    assert contexts == []

    accepted_task = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    accepted = await client.post(
        f"/api/v1/ingest/{accepted_task}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_confirm_payload(target_scope="personal"),
    )
    assert accepted.status_code == 200
    assert len(contexts) == 1
    assert contexts[0].task.id == uuid.UUID(accepted_task)
    assert contexts[0].scope == "personal"
    assert contexts[0].project_id is None
    assert contexts[0].caller.user_id == USER_CONSULTANT


async def test_confirm_project_non_member_rejected_consultant_waits_for_review(client):
    """项目入库：非成员被拒；普通成员提交后等待审批且资产不可见。"""
    # 非成员项目 Beta（consultant 在 Beta 为 inactive）→ 403
    task1 = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    r1 = await client.post(
        f"/api/v1/ingest/{task1}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_confirm_payload(target_scope="project", target_project_id=str(PROJECT_BETA)),
    )
    assert r1.status_code == 403
    assert r1.json()["detail"]["denied_reason"] == "project_membership_required"

    # 成员项目 Alpha → 仅创建持久化审批任务，不创建可见资产。
    task2 = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    r2 = await client.post(
        f"/api/v1/ingest/{task2}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_confirm_payload(
            title="Alpha 入库项目资产",
            target_scope="project",
            target_project_id=str(PROJECT_ALPHA),
        ),
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "waiting_review"
    assert r2.json()["result_asset_id"] is None
    assert r2.json()["review_id"] is not None
    items = (await client.get(f"{KN}?scope=project", headers=_hdr(USER_CONSULTANT))).json()["items"]
    assert all(i["title"] != "Alpha 入库项目资产" for i in items)


async def test_project_manager_self_submission_is_confirmed_directly(client):
    """目标项目经理提交自己的项目知识，后端明确走经理自确认路径。"""
    task_id = (await _create_task(client, USER_PROJECT_MANAGER)).json()["ingest_task_id"]
    response = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_PROJECT_MANAGER),
        json=_confirm_payload(
            title="经理自确认项目资产",
            target_scope="project",
            target_project_id=str(PROJECT_ALPHA),
        ),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["result_asset_id"] is not None
    assert response.json()["review_id"] is None
    items = (await client.get(f"{KN}?scope=project", headers=_hdr(USER_PROJECT_MANAGER))).json()[
        "items"
    ]
    assert any(item["title"] == "经理自确认项目资产" for item in items)


async def test_consultant_company_confirm_rejected_boss_ok(client):
    """consultant 直接确认 company 资产被拒；boss 可确认。"""
    task1 = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    r1 = await client.post(
        f"/api/v1/ingest/{task1}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_confirm_payload(target_scope="company"),
    )
    assert r1.status_code == 403
    assert r1.json()["detail"]["denied_reason"] == "company_confirmation_requires_governance"

    task2 = (await _create_task(client, USER_BOSS)).json()["ingest_task_id"]
    r2 = await client.post(
        f"/api/v1/ingest/{task2}/confirm",
        headers=_hdr(USER_BOSS),
        json=_confirm_payload(title="公司级入库资产", target_scope="company"),
    )
    assert r2.status_code == 200
    company_detail = (
        await client.get(f"{KN}/{r2.json()['result_asset_id']}", headers=_hdr(USER_BOSS))
    ).json()
    assert company_detail["visibility"] == "public"


async def test_company_confirm_requires_ready_company_kb(client, db_session):
    await db_session.execute(delete(WeknoraKbMapping).where(WeknoraKbMapping.scope == "company"))
    await db_session.commit()
    task_id = (await _create_task(client, USER_BOSS)).json()["ingest_task_id"]
    response = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_BOSS),
        json=_confirm_payload(title="公司库未就绪", target_scope="company"),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["denied_reason"] == "company_kb_not_ready"
    assert "wk-kb" not in response.text


async def test_confirm_l4_redacted_summary_no_key_points(client):
    """L4 detail returns a complete redacted detailed summary and a distinct short variant."""
    sensitive_customer = "测试敏感客户"
    sensitive_email = "hidden@example.com"
    sensitive_phone = "13812345678"
    safe_tail = "AUTHORIZED-SUMMARY-END"
    detailed = (
        f"客户名称：{sensitive_customer}，联系人邮箱 {sensitive_email}，电话 {sensitive_phone}。"
        + "这是经过授权后可以完整展示的业务方法说明。" * 20
        + safe_tail
    )
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    r = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_confirm_payload(
            title="个人 L4 资产",
            one_liner=f"客户名称：{sensitive_customer}的安全短摘要",
            summary=detailed,
            key_points=["不得返回的敏感要点"],
            target_scope="personal",
            confidentiality_level="L4",
        ),
    )
    asset_id = r.json()["result_asset_id"]
    detail = (await client.get(f"{KN}/{asset_id}", headers=_hdr(USER_CONSULTANT))).json()
    assert detail["summary"] is not None
    assert detail["summary"]["one_liner"].startswith("（脱敏）")
    assert len(detail["summary"]["one_liner"]) <= 204
    assert len(detail["summary"]["detailed"]) > 200
    assert detail["summary"]["detailed"].endswith(safe_tail)
    assert detail["summary"]["one_liner"] != detail["summary"]["detailed"]
    assert detail["summary"]["key_points"] == []
    for sensitive in (sensitive_customer, sensitive_email, sensitive_phone, "不得返回的敏感要点"):
        assert sensitive not in detail["summary"]["one_liner"]
        assert sensitive not in detail["summary"]["detailed"]


async def test_second_confirm_returns_409(client):
    """二次 confirm 同一任务返回 409，不重复创建资产。"""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    p = _confirm_payload(target_scope="personal")
    r1 = await client.post(
        f"/api/v1/ingest/{task_id}/confirm", headers=_hdr(USER_CONSULTANT), json=p
    )
    assert r1.status_code == 200
    r2 = await client.post(
        f"/api/v1/ingest/{task_id}/confirm", headers=_hdr(USER_CONSULTANT), json=p
    )
    assert r2.status_code == 409
    assert r2.json()["detail"]["denied_reason"] == "ingest_already_confirmed"


async def test_confirm_by_other_non_governance_user_forbidden(client):
    """顾问 A 创建的任务，另一名非治理业务用户（经理 B）确认应被拒，且不创建资产。"""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    r = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_PROJECT_MANAGER),
        json=_confirm_payload(title="他人越权确认", target_scope="personal"),
    )
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "ingest_confirm_forbidden"
    # 经理 B 的个人知识列表不应出现该资产（未创建）。
    my = (await client.get(MY, headers=_hdr(USER_PROJECT_MANAGER))).json()
    assert all(i["title"] != "他人越权确认" for i in my["items"])


async def test_governance_can_confirm_others_task(client):
    """业务治理角色（boss）可确认他人创建的任务。"""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    r = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_BOSS),
        json=_confirm_payload(title="治理代确认资产", target_scope="company"),
    )
    assert r.status_code == 200


async def test_confirm_invalid_enum_returns_422(client):
    """非法 enum 值（保密级别 L9）返回 422，不创建资产。"""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    r = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_confirm_payload(target_scope="personal", confidentiality_level="L9"),
    )
    assert r.status_code == 422


async def test_confirm_rejects_deprecated_client_controlled_fields(client):
    """Removed governance fields must fail loudly so stale clients cannot drift silently."""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    payload = _confirm_payload(target_scope="personal")
    payload.update(
        {
            "asset_type": "methodology",
            "visibility": "public",
            "ai_access_level": "A2",
            "lifecycle_phase_key": "诊断",
        }
    )

    response = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=payload,
    )

    assert response.status_code == 422
    rejected_fields = {
        error["loc"][-1]
        for error in response.json()["detail"]
        if error["type"] == "extra_forbidden"
    }
    assert rejected_fields == {
        "asset_type",
        "visibility",
        "ai_access_level",
        "lifecycle_phase_key",
    }


async def test_confirm_visibility_is_derived_from_personal_scope(client):
    """The destination determines visibility without accepting a client override."""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    r = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_confirm_payload(title="服务端派生可见性的资产", target_scope="personal"),
    )
    assert r.status_code == 200, r.text
    asset_id = r.json()["result_asset_id"]
    detail = (await client.get(f"{KN}/{asset_id}", headers=_hdr(USER_CONSULTANT))).json()
    assert detail["visibility"] == "confidential"


async def test_upload_persists_real_file_and_no_leak(client):
    """上传真实文件：字节确实落盘到受控存储；响应不含存储引用 / 路径 / URL。"""
    resp = await client.post(
        UPLOAD,
        headers=_hdr(USER_CONSULTANT),
        files={"file": ("方案.pdf", b"hello-bytes-1234567890", "application/pdf")},
    )
    assert resp.status_code == 200
    text = resp.text
    # 响应只含安全元数据，绝不含内部引用 / 路径 / URL。
    for token in [
        "source_file_ref",
        "storage_ref",
        "internal://",
        "file://",
        "s3://",
        "oss://",
        "http://",
        "https://",
        str(client._kap_storage.root),
    ]:
        assert token not in text, f"响应不应泄露 {token}"

    # 存储目录中确实新增了一个非空文件（字节真的落盘）。
    files = [p for p in client._kap_storage.root.rglob("*") if p.is_file()]
    assert len(files) >= 1
    assert any(p.read_bytes() == b"hello-bytes-1234567890" for p in files)


async def test_upload_empty_file_rejected(client):
    """空文件被拒（422 empty_file），不创建任务、不落盘。"""
    resp = await client.post(
        UPLOAD,
        headers=_hdr(USER_CONSULTANT),
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["denied_reason"] == "empty_file"
    files = [p for p in client._kap_storage.root.rglob("*") if p.is_file()]
    assert files == []


async def test_upload_path_traversal_filename_normalized(client):
    """路径穿越文件名被归一化：不逃逸存储根目录，落盘文件名安全。"""
    resp = await client.post(
        UPLOAD,
        headers=_hdr(USER_CONSULTANT),
        files={"file": ("../../../etc/passwd", b"payload-bytes", "application/octet-stream")},
    )
    assert resp.status_code == 200
    root = client._kap_storage.root
    files = [p for p in root.rglob("*") if p.is_file()]
    assert len(files) == 1
    # 落盘路径仍在存储根目录下，且文件名不含路径分隔/穿越。
    assert str(files[0].resolve()).startswith(str(root))
    assert files[0].name == "etcpasswd" or "passwd" in files[0].name
    assert ".." not in files[0].name


async def test_admin_denied_upload_does_not_persist_file(client):
    """纯 admin 上传被拒（403），且不落盘任何字节。"""
    resp = await client.post(
        UPLOAD,
        headers=_hdr(USER_ADMIN_ONLY),
        files={"file": ("x.pdf", b"should-not-persist", "application/pdf")},
    )
    assert resp.status_code == 403
    files = [p for p in client._kap_storage.root.rglob("*") if p.is_file()]
    assert files == []


def test_storage_resolve_path_rejects_escape(tmp_path):
    """resolve_path 不能被路径穿越 / 兄弟前缀绕过到存储根之外。"""
    storage = LocalFileStorage(tmp_path / "root")
    # 同时创建一个共享前缀的兄弟目录，确保不是靠"不存在"才被拒。
    (tmp_path / "root2").mkdir(parents=True, exist_ok=True)
    (tmp_path / "root").mkdir(parents=True, exist_ok=True)

    # 路径穿越到兄弟目录（root2 与 root 共享字符串前缀）。
    with pytest.raises(StorageError):
        storage.resolve_path("internal://../root2/evil.pdf")
    # 直接穿越到上级。
    with pytest.raises(StorageError):
        storage.resolve_path("internal://../../etc/passwd")
    # 合法引用仍可解析，且落在 root 内。
    ok = storage.resolve_path("internal://abc123/file.pdf")
    assert ok.resolve().is_relative_to((tmp_path / "root").resolve())


def test_storage_save_stays_within_root(tmp_path):
    """save 的落盘路径始终在存储根之内，且文件名归一化无穿越。"""
    storage = LocalFileStorage(tmp_path / "root")
    ref = storage.save(b"bytes", original_name="../../../etc/passwd")
    path = storage.resolve_path(ref)
    assert path.resolve().is_relative_to((tmp_path / "root").resolve())
    assert ".." not in path.name


async def test_upload_extraction_success_content_based(client):
    """抽取成功：ai-result 含基于内容的建议 + 抽取预览（创建人完整视图）。"""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    r = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    assert r.status_code == 200
    body = r.json()
    assert body["extraction_status"] == "extracted"
    # suggested_title 仅为干净主题；完整规范名由确认阶段的新规则生成。
    assert body["suggested_title"] == body["naming_parsed_fields"]["topic"]
    assert not body["suggested_title"].startswith("【")
    # 抽取首行进入一句话摘要字段，不抢占标题。
    assert body["suggested_one_liner"] == "零售数字化转型方案"
    assert body["suggested_title"] != body["suggested_one_liner"]
    assert body["extracted_char_count"] > 0
    assert body["extracted_text_preview"] and "零售数字化转型" in body["extracted_text_preview"]


async def test_legacy_title_projection_is_clean_consistent_and_read_only(client, db_session):
    """历史完整规范名只在持久化兼容数据中保留，所有待确认读模型投影同一主题。"""
    task_id = uuid.UUID((await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"])
    ai = (
        await db_session.execute(
            select(IngestTaskAiResult).where(IngestTaskAiResult.ingest_task_id == task_id)
        )
    ).scalar_one()
    legacy_title = "【公司知识-制度规范】季度复盘_华东区_20240520_V1_L2"
    ai.suggested_title = legacy_title
    ai.naming_parsed_fields = {
        key: value for key, value in (ai.naming_parsed_fields or {}).items() if key != "topic"
    }
    await db_session.commit()

    detail = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    pending = await client.get("/api/v1/ingest/pending", headers=_hdr(USER_CONSULTANT))
    pending_item = next(item for item in pending.json()["items"] if item["id"] == str(task_id))

    assert detail.status_code == 200
    assert detail.json()["suggested_title"] == "季度复盘"
    assert pending_item["suggested_title"] == "季度复盘"
    # 原始值只作为受控兼容元数据保留，不再成为任一读模型的建议主题。
    compatibility_title = detail.json()["naming_parsed_fields"]["normalized_title"]
    assert compatibility_title != detail.json()["suggested_title"]
    assert pending_item["naming_parsed_fields"]["normalized_title"] == compatibility_title
    await db_session.refresh(ai)
    assert ai.suggested_title == legacy_title


async def test_upload_markdown_enters_confirmation_with_extracted_text(client):
    """Markdown 上传走纯文本抽取成功路径，可进入资产化确认。"""
    resp = await client.post(
        UPLOAD,
        headers=_hdr(USER_CONSULTANT),
        files={"file": ("project-review.md", _MD_BYTES, "text/markdown")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending_confirmation"

    task_id = body["ingest_task_id"]
    ai = (
        await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    ).json()
    assert ai["status"] == "pending_confirmation"
    assert ai["extraction_status"] == "extracted"
    assert ai["extracted_char_count"] > 0
    assert ai["extracted_text_preview"] and "项目复盘" in ai["extracted_text_preview"]


async def test_pending_list_derives_safe_batch_confirmation_capability(client, db_session):
    upload = await client.post(
        UPLOAD,
        headers=_hdr(USER_CONSULTANT),
        files={
            "file": (
                "legacy-notes.md",
                _TXT_BYTES,
                "application/octet-stream",
            )
        },
    )
    assert upload.status_code == 200
    task_id = uuid.UUID(upload.json()["ingest_task_id"])

    task = await db_session.get(IngestTask, task_id)
    ai = (
        await db_session.execute(
            select(IngestTaskAiResult).where(IngestTaskAiResult.ingest_task_id == task_id)
        )
    ).scalar_one()
    original_title = ai.suggested_title
    original_summary = ai.suggested_summary
    original_one_liner = ai.suggested_one_liner
    assert original_title and (original_summary or original_one_liner)

    task.status = "pending"
    ai.extraction_status = "unsupported"
    ai.llm_provider = "test-provider"
    ai.naming_parsed_fields = {
        **(ai.naming_parsed_fields or {}),
        "generation_status": "generated",
        "summary_generated": True,
    }
    await db_session.commit()
    ready = await client.get("/api/v1/ingest/pending", headers=_hdr(USER_CONSULTANT))
    ready_item = next(item for item in ready.json()["items"] if item["id"] == str(task_id))
    assert ready_item["status"] == "pending"
    assert ready_item["extraction_status"] == "unsupported"
    assert ready_item["suggestion_generation_status"] == "needs_manual_completion"
    assert ready_item["can_batch_confirm"] is True
    assert ready_item["can_batch_reject"] is False
    await db_session.refresh(task)
    assert task.status == "pending"  # GET compatibility projection never writes state.

    ai.llm_provider = None
    ai.naming_parsed_fields = {
        key: value
        for key, value in (ai.naming_parsed_fields or {}).items()
        if key not in {"generation_status", "summary_generated"}
    }
    ai.extraction_status = "legacy_extracted"
    await db_session.commit()
    old_metadata = await client.get("/api/v1/ingest/pending", headers=_hdr(USER_CONSULTANT))
    old_metadata_item = next(
        item for item in old_metadata.json()["items"] if item["id"] == str(task_id)
    )
    assert old_metadata_item["suggestion_generation_status"] != "generated"
    assert old_metadata_item["can_batch_confirm"] is True
    assert old_metadata_item["can_batch_reject"] is False

    task.status = "pending_confirmation"
    await db_session.commit()
    pending_confirmation = await client.get("/api/v1/ingest/pending", headers=_hdr(USER_CONSULTANT))
    pending_confirmation_item = next(
        item for item in pending_confirmation.json()["items"] if item["id"] == str(task_id)
    )
    assert pending_confirmation_item["can_batch_confirm"] is True
    assert pending_confirmation_item["can_batch_reject"] is True

    task.status = "processing"
    await db_session.commit()
    processing = await client.get("/api/v1/ingest/pending", headers=_hdr(USER_CONSULTANT))
    processing_item = next(
        item for item in processing.json()["items"] if item["id"] == str(task_id)
    )
    assert processing_item["can_batch_confirm"] is False
    assert processing_item["can_batch_reject"] is False

    task.status = "pending_confirmation"
    ai.suggested_title = None
    await db_session.commit()
    incomplete = await client.get("/api/v1/ingest/pending", headers=_hdr(USER_CONSULTANT))
    incomplete_item = next(
        item for item in incomplete.json()["items"] if item["id"] == str(task_id)
    )
    # 旧 suggested_title 缺失时仍可从结构化 topic / 文件名安全回退主题。
    assert incomplete_item["can_batch_confirm"] is True
    assert incomplete_item["can_batch_reject"] is True

    ai.suggested_title = original_title
    ai.suggested_summary = None
    ai.suggested_one_liner = None
    await db_session.commit()
    missing_summary = await client.get("/api/v1/ingest/pending", headers=_hdr(USER_CONSULTANT))
    missing_summary_item = next(
        item for item in missing_summary.json()["items"] if item["id"] == str(task_id)
    )
    assert missing_summary_item["can_batch_confirm"] is False
    assert missing_summary_item["can_batch_reject"] is True

    ai.suggested_summary = original_summary
    ai.suggested_one_liner = original_one_liner
    task.status = "failed"
    await db_session.commit()
    failed = await client.get("/api/v1/ingest/pending", headers=_hdr(USER_CONSULTANT))
    failed_item = next(item for item in failed.json()["items"] if item["id"] == str(task_id))
    assert failed_item["can_batch_confirm"] is False
    assert failed_item["can_batch_reject"] is True

    task.status = "waiting_review"
    await db_session.commit()
    waiting_review = await client.get("/api/v1/ingest/pending", headers=_hdr(USER_CONSULTANT))
    waiting_review_item = next(
        item for item in waiting_review.json()["items"] if item["id"] == str(task_id)
    )
    assert waiting_review_item["can_batch_confirm"] is False
    assert waiting_review_item["can_batch_reject"] is True

    task.status = "rejected"
    await db_session.commit()
    rejected = await client.get("/api/v1/ingest/pending", headers=_hdr(USER_CONSULTANT))
    rejected_item = next(item for item in rejected.json()["items"] if item["id"] == str(task_id))
    assert rejected_item["can_batch_confirm"] is True
    assert rejected_item["can_batch_reject"] is True

    ai.suggested_summary = None
    ai.suggested_one_liner = None
    await db_session.commit()
    rejected_without_summary = await client.get(
        "/api/v1/ingest/pending", headers=_hdr(USER_CONSULTANT)
    )
    rejected_without_summary_item = next(
        item for item in rejected_without_summary.json()["items"] if item["id"] == str(task_id)
    )
    assert rejected_without_summary_item["can_batch_confirm"] is False
    assert rejected_without_summary_item["can_batch_reject"] is True

    task.status = "completed"
    await db_session.commit()
    completed = await client.get("/api/v1/ingest/pending", headers=_hdr(USER_CONSULTANT))
    completed_item = next(item for item in completed.json()["items"] if item["id"] == str(task_id))
    assert completed_item["can_batch_confirm"] is False
    assert completed_item["can_batch_reject"] is False


async def test_upload_unsupported_still_pending(client):
    """不支持类型：标 unsupported，但任务仍待确认（不阻断人工补全）。"""
    resp = await client.post(
        UPLOAD,
        headers=_hdr(USER_CONSULTANT),
        files={"file": ("sheet.xlsx", b"PK\x03\x04binary-xlsx", "application/octet-stream")},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending_confirmation"
    task_id = resp.json()["ingest_task_id"]
    ai = (
        await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    ).json()
    assert ai["extraction_status"] == "unsupported"
    assert "人工补全" in ai["suggested_summary"]


async def test_upload_failed_extraction_persists_and_audits_no_leak(client):
    """损坏 PDF：状态 failed + 持久化错误 + ingest.failed 审计，且审计无抽取全文 / 内部引用。"""
    resp = await client.post(
        UPLOAD,
        headers={**_hdr(USER_CONSULTANT), "X-Trace-Id": "trc-extract-fail"},
        files={"file": ("broken.pdf", b"not a real pdf payload", "application/pdf")},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"
    task_id = resp.json()["ingest_task_id"]
    ai = (
        await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    ).json()
    assert ai["extraction_status"] == "failed"
    assert ai["error_type"] == "extraction_failed"
    assert ai["error_message"]

    # 审计 trace（治理视图）含 ingest.failed，且不泄露抽取内容 / 内部引用。
    trace = await client.get("/api/v1/admin/audit/trace/trc-extract-fail", headers=_hdr(USER_BOSS))
    actions = {e["action"] for e in trace.json()["items"]}
    assert "ingest.failed" in actions
    for token in ["internal://", "source_file_ref", "storage_ref", "not a real pdf payload"]:
        assert token not in trace.text


async def test_admin_view_hides_extracted_fulltext(client):
    """admin 元数据视图不返回抽取全文 / 业务建议正文，但可见抽取状态。"""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    r = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_ADMIN_ONLY))
    assert r.status_code == 200
    body = r.json()
    assert body["suggested_title"] is None
    assert body["suggested_summary"] is None
    assert body["extracted_text_preview"] is None
    assert body["extraction_status"] == "extracted"  # 运营元数据仍可见
    assert "零售数字化转型" not in r.text  # 抽取全文不出现


async def test_duplicate_content_soft_hint_non_blocking(client):
    """相同内容哈希：第二次上传给非阻塞软提示，指向首个任务，不拦截。"""
    first = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    second_resp = await _create_task(client, USER_CONSULTANT)
    assert second_resp.status_code == 200
    assert second_resp.json()["status"] == "pending_confirmation"  # 不阻断
    second = second_resp.json()["ingest_task_id"]
    ai = (
        await client.get(f"/api/v1/ingest/{second}/ai-result", headers=_hdr(USER_CONSULTANT))
    ).json()
    assert ai["is_possible_duplicate"] is True
    assert ai["duplicate_of_task_id"] == first


async def test_admin_ingest_list_operational_only(client):
    """admin 可看入库运营列表，不含 source_file_ref / storage_ref。"""
    await _create_task(client, USER_CONSULTANT)
    resp = await client.get("/api/v1/admin/ingest", headers=_hdr(USER_ADMIN_ONLY))
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1
    assert "source_file_ref" not in resp.text
    assert "storage_ref" not in resp.text


# ────────────────────────── 删除待确认任务 ──────────────────────────


async def test_rejected_history_can_confirm_or_be_permanently_rejected(client, db_session):
    confirm_task_id = uuid.UUID(
        (await _create_task(client, USER_CONSULTANT, "confirm-rejected.md")).json()[
            "ingest_task_id"
        ]
    )
    delete_task_id = uuid.UUID(
        (await _create_task(client, USER_CONSULTANT, "delete-rejected.md")).json()["ingest_task_id"]
    )
    confirm_task = await db_session.get(IngestTask, confirm_task_id)
    delete_task = await db_session.get(IngestTask, delete_task_id)
    confirm_task.status = "rejected"
    delete_task.status = "rejected"
    await db_session.commit()

    confirmed = await client.post(
        f"/api/v1/ingest/{confirm_task_id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_confirm_payload(target_scope="personal"),
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "completed"

    deleted = await client.delete(f"/api/v1/ingest/{delete_task_id}", headers=_hdr(USER_CONSULTANT))
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True


async def test_delete_pending_task_by_creator_succeeds(client):
    """创建人可删除自己未确认的待确认任务，删除后不再出现在列表。"""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    # 先确认任务在待确认列表。
    pending = await client.get("/api/v1/ingest/pending", headers=_hdr(USER_CONSULTANT))
    assert str(task_id) in {i["id"] for i in pending.json()["items"]}
    # 删除。
    resp = await client.delete(f"/api/v1/ingest/{task_id}", headers=_hdr(USER_CONSULTANT))
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    # 删除后不在待确认列表。
    pending2 = await client.get("/api/v1/ingest/pending", headers=_hdr(USER_CONSULTANT))
    assert str(task_id) not in {i["id"] for i in pending2.json()["items"]}


async def test_delete_pending_task_by_others_forbidden(client):
    """非创建人不能删除他人任务（包括治理角色）。"""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    # 经理 B 无权删除顾问的任务。
    resp = await client.delete(f"/api/v1/ingest/{task_id}", headers=_hdr(USER_PROJECT_MANAGER))
    assert resp.status_code == 403
    assert resp.json()["detail"]["denied_reason"] == "ingest_delete_forbidden"
    # 治理角色也无权删除他人任务。
    resp2 = await client.delete(f"/api/v1/ingest/{task_id}", headers=_hdr(USER_BOSS))
    assert resp2.status_code == 403
    assert resp2.json()["detail"]["denied_reason"] == "ingest_delete_forbidden"
    # 任务仍在。
    pending = await client.get("/api/v1/ingest/pending", headers=_hdr(USER_CONSULTANT))
    assert str(task_id) in {i["id"] for i in pending.json()["items"]}


async def test_delete_confirmed_task_forbidden(client):
    """已确认入库的任务不可删除。"""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_confirm_payload(target_scope="personal"),
    )
    resp = await client.delete(f"/api/v1/ingest/{task_id}", headers=_hdr(USER_CONSULTANT))
    assert resp.status_code == 409
    assert resp.json()["detail"]["denied_reason"] == "ingest_already_confirmed"


async def test_delete_pending_cleans_up_storage(client):
    """删除待确认任务后，DB 记录被删除，存储文件清理为 best-effort。"""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    # 确保存储中存在文件（上传成功）。
    files_before = [p for p in client._kap_storage.root.rglob("*") if p.is_file()]
    assert len(files_before) >= 1
    await client.delete(f"/api/v1/ingest/{task_id}", headers=_hdr(USER_CONSULTANT))
    # 核心断言：DB 记录已删除，不在待确认列表。
    pending = await client.get("/api/v1/ingest/pending", headers=_hdr(USER_CONSULTANT))
    assert str(task_id) not in {i["id"] for i in pending.json()["items"]}


async def test_delete_pending_by_admin_403(client):
    """纯 admin 没有删除业务的权限。"""
    task_id = (await _create_task(client, USER_BOSS)).json()["ingest_task_id"]
    resp = await client.delete(f"/api/v1/ingest/{task_id}", headers=_hdr(USER_ADMIN_ONLY))
    assert resp.status_code == 403
    assert resp.json()["detail"]["denied_reason"] == "ingest_delete_forbidden"


@pytest.mark.parametrize(
    "database_error",
    [
        OperationalError(
            "SELECT private_lock_target",
            None,
            Exception("PRIVATE database lock wait detail"),
        ),
        SQLAlchemyTimeoutError("PRIVATE connection pool timeout detail"),
    ],
)
async def test_delete_pending_database_unavailable_returns_safe_stable_503(
    client, monkeypatch, database_error
):
    async def fail_while_loading(*_args, **_kwargs):
        raise database_error

    monkeypatch.setattr(ingest_service, "_load_task", fail_while_loading)

    response = await client.delete(f"/api/v1/ingest/{uuid.uuid4()}", headers=_hdr(USER_CONSULTANT))

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "denied_reason": "ingest_delete_temporarily_unavailable",
        "message": "任务关联清理暂时不可用，请稍后重试",
    }
    assert "private" not in response.text.lower()
    assert "lock" not in response.text.lower()
    assert "connection" not in response.text.lower()

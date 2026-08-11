"""Project-scoped ingest approval state machine and authorization boundaries."""

from __future__ import annotations

import uuid

import pytest
from conftest import patch_default_model
from sqlalchemy import func, select, update

from app.main import app
from app.models.audit import AuditEvent
from app.models.identity import ProjectMember
from app.models.ingest import IngestTask, IngestTaskDerivative
from app.models.knowledge import KnowledgeAsset
from app.models.review import CompanyAssetReviewDecision, ReviewTask
from app.seed.dev_seed import (
    PROJECT_ALPHA,
    PROJECT_BETA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_CONSULTANT_ADMIN,
    USER_DIRECTOR,
    USER_PROJECT_MANAGER,
)
from app.services.weknora_client import WeKnoraError, get_weknora_client

UPLOAD = "/api/v1/ingest/upload"
REVIEWS = "/api/v1/reviews"
KNOWLEDGE = "/api/v1/knowledge"
_CONTENT = "项目知识审批测试内容，只能在审批通过后进入项目知识库。".encode()


class _ApprovalWeKnora:
    def __init__(self, *, fail: bool) -> None:
        self.fail = fail
        self.upload_count = 0

    async def create_kb(self, **_):
        return "kb-project"

    async def initialize_kb(self, *_args, **_kwargs):
        return None

    async def get_initialization_config(self, *_args, **_kwargs):
        return {}

    async def upload_file(self, **_):
        if self.fail:
            raise WeKnoraError("weknora_down", "SECRET-LIKE upstream message")
        self.upload_count += 1
        return {"id": "doc-approved", "parse_status": "processing", "file_hash": "h"}

    async def get_knowledge(self, knowledge_id, **_):
        return {"id": knowledge_id, "parse_status": "completed"}


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


def _payload(title: str = "待审批项目知识") -> dict:
    return {
        "title": title,
        "summary": "经人工确认的安全摘要",
        "tags": ["项目知识"],
        "target_scope": "project",
        "target_project_id": str(PROJECT_ALPHA),
        "target_zone": "material",
        "confidentiality_level": "L2",
    }


async def _submit(client, *, title: str = "待审批项目知识") -> tuple[str, str]:
    uploaded = await client.post(
        UPLOAD,
        headers=_hdr(USER_CONSULTANT),
        files={"file": ("approval.txt", _CONTENT, "text/plain")},
    )
    assert uploaded.status_code == 200
    task_id = uploaded.json()["ingest_task_id"]
    confirmed = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_payload(title),
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "waiting_review"
    assert confirmed.json()["result_asset_id"] is None
    return task_id, confirmed.json()["review_id"]


async def test_consultant_submission_persists_review_without_visible_asset(client, db_session):
    task_id, review_id = await _submit(client)

    review = await db_session.get(ReviewTask, uuid.UUID(review_id))
    assert review is not None
    assert review.review_type == "project_ingest_approval"
    assert review.status == "pending_reviewer"
    assert review.submitted_by == USER_CONSULTANT
    assert review.target_project_id == PROJECT_ALPHA
    assert review.target_asset_id is None
    assert review.source_ingest_task_id is not None
    assert review.confirmation_snapshot["title"] == "待审批项目知识"
    snapshot = str(review.confirmation_snapshot).lower()
    assert "source_file_ref" not in snapshot
    assert "storage_ref" not in snapshot
    assert "weknora" not in snapshot

    task = await db_session.get(IngestTask, uuid.UUID(task_id))
    assert task is not None and task.status == "waiting_review"
    assert task.result_asset_id is None
    visible = (await client.get(KNOWLEDGE, headers=_hdr(USER_CONSULTANT))).json()["items"]
    assert all(item["title"] != "待审批项目知识" for item in visible)


async def test_target_project_manager_approves_then_duplicate_is_audited(client, db_session):
    _, review_id = await _submit(client, title="审批后可见项目知识")
    approved = await client.post(
        f"{REVIEWS}/{review_id}/approve",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={"review_comment": "内容有效"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    asset_id = approved.json()["target_asset_id"]

    detail = await client.get(f"{KNOWLEDGE}/{asset_id}", headers=_hdr(USER_CONSULTANT))
    assert detail.status_code == 200
    assert detail.json()["title"] == "审批后可见项目知识"
    asset = await db_session.get(KnowledgeAsset, uuid.UUID(asset_id))
    assert asset is not None and asset.asset_status == "active"

    duplicate = await client.post(
        f"{REVIEWS}/{review_id}/approve",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={},
    )
    assert duplicate.status_code == 409
    count = await db_session.scalar(
        select(func.count())
        .select_from(KnowledgeAsset)
        .where(KnowledgeAsset.id == uuid.UUID(asset_id))
    )
    assert count == 1
    conflict = await db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.target_id == uuid.UUID(review_id),
            AuditEvent.extra["denied_reason"].as_string() == "review_decision_conflict",
        )
    )
    assert conflict is not None


async def test_project_manager_rejects_without_exposing_original(client, db_session):
    task_id, review_id = await _submit(client, title="被驳回项目知识")
    response = await client.post(
        f"{REVIEWS}/{review_id}/reject",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={"review_comment": "不符合项目知识标准"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["target_asset_id"] is None
    assert "approval.txt" not in response.text
    assert _CONTENT.decode() not in response.text
    task = await db_session.get(IngestTask, uuid.UUID(task_id))
    assert task is not None and task.status == "rejected"
    assert task.source_file_ref is not None
    visible = (await client.get(KNOWLEDGE, headers=_hdr(USER_CONSULTANT))).json()["items"]
    assert all(item["title"] != "被驳回项目知识" for item in visible)


async def test_creator_permanently_deletes_rejected_project_ingest_dependencies(client, db_session):
    task_id, review_id = await _submit(client, title="应永久删除的错误上传")
    rejected = await client.post(
        f"{REVIEWS}/{review_id}/reject",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={"review_comment": "上传内容错误"},
    )
    assert rejected.status_code == 200

    # Even an unexpected dependent decision must be cleaned before the dedicated
    # project-ingest review, otherwise the review FK recreates the production 500.
    decision = CompanyAssetReviewDecision(
        review_task_id=uuid.UUID(review_id),
        required_role="boss",
        decision="confirmed",
        actor_user_id=USER_BOSS,
    )
    db_session.add(decision)
    await db_session.commit()
    decision_id = decision.id

    deleted = await client.delete(f"/api/v1/ingest/{task_id}", headers=_hdr(USER_CONSULTANT))

    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}
    db_session.expire_all()
    assert await db_session.get(IngestTask, uuid.UUID(task_id)) is None
    assert await db_session.get(ReviewTask, uuid.UUID(review_id)) is None
    assert await db_session.get(CompanyAssetReviewDecision, decision_id) is None
    audit = (
        (
            await db_session.execute(
                select(AuditEvent)
                .where(
                    AuditEvent.action == "ingest.task_deleted",
                    AuditEvent.target_id == uuid.UUID(task_id),
                )
                .order_by(AuditEvent.created_at.desc())
            )
        )
        .scalars()
        .first()
    )
    assert audit is not None
    assert audit.after_snapshot == {"result_category": "permanently_deleted"}
    serialized_audit = str(
        {"before": audit.before_snapshot, "after": audit.after_snapshot, "extra": audit.extra}
    ).lower()
    assert "source_file_ref" not in serialized_audit
    assert "storage_ref" not in serialized_audit
    assert "approval.txt" not in serialized_audit


async def test_consultant_admin_and_other_project_manager_cannot_decide(client, db_session):
    _, review_id = await _submit(client)
    consultant = await client.post(
        f"{REVIEWS}/{review_id}/approve", headers=_hdr(USER_CONSULTANT), json={}
    )
    assert consultant.status_code == 403
    admin = await client.post(
        f"{REVIEWS}/{review_id}/approve", headers=_hdr(USER_ADMIN_ONLY), json={}
    )
    assert admin.status_code == 403

    db_session.add(
        ProjectMember(
            user_id=USER_CONSULTANT_ADMIN,
            project_id=PROJECT_BETA,
            project_role="project_manager",
            status="active",
        )
    )
    await db_session.commit()
    await client.post("/api/v1/auth/login", json={"email": "dual.f@dev.local"})
    csrf = (await client.get("/api/v1/auth/csrf")).json()["csrf_token"]
    switched = await client.post(
        "/api/v1/auth/active-company-role",
        headers={"X-CSRF-Token": csrf},
        json={"company_role": "consultant"},
    )
    assert switched.status_code == 200
    other_manager = await client.post(
        f"{REVIEWS}/{review_id}/approve",
        headers={"X-CSRF-Token": csrf},
        json={},
    )
    assert other_manager.status_code == 403
    assert other_manager.json()["detail"]["denied_reason"] == "project_ingest_review_forbidden"


@pytest.mark.parametrize("approver", [USER_BOSS, USER_DIRECTOR])
async def test_governance_roles_cannot_bypass_project_manager(client, approver):
    _, review_id = await _submit(client, title=f"治理兜底审批-{approver}")
    response = await client.post(f"{REVIEWS}/{review_id}/approve", headers=_hdr(approver), json={})
    assert response.status_code == 403
    assert response.json()["detail"]["denied_reason"] == "project_ingest_review_forbidden"


async def test_inflight_approval_claim_blocks_competing_decision(client, db_session):
    _, review_id = await _submit(client, title="并发审批项目知识")
    rid = uuid.UUID(review_id)
    claim = await db_session.execute(
        update(ReviewTask)
        .where(ReviewTask.id == rid, ReviewTask.status == "pending_reviewer")
        .values(status="approving")
    )
    assert getattr(claim, "rowcount", 0) == 1
    await db_session.commit()

    competing = await client.post(
        f"{REVIEWS}/{review_id}/approve",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={},
    )
    assert competing.status_code == 409

    await db_session.execute(
        update(ReviewTask).where(ReviewTask.id == rid).values(status="pending_reviewer")
    )
    await db_session.commit()
    winner = await client.post(
        f"{REVIEWS}/{review_id}/approve",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={},
    )
    assert winner.status_code == 200
    review = await db_session.get(ReviewTask, uuid.UUID(review_id))
    assert review is not None and review.status == "approved"
    count = await db_session.scalar(
        select(func.count())
        .select_from(KnowledgeAsset)
        .where(
            KnowledgeAsset.project_id == PROJECT_ALPHA, KnowledgeAsset.title == "并发审批项目知识"
        )
    )
    assert count == 1


async def test_index_failure_stays_invisible_and_retry_reuses_asset(
    client, db_session, monkeypatch
):
    monkeypatch.setattr("app.services.ingest.weknora_enabled", lambda: True)
    patch_default_model(monkeypatch)
    failing = _ApprovalWeKnora(fail=True)
    app.dependency_overrides[get_weknora_client] = lambda: failing
    _, review_id = await _submit(client, title="失败后重试项目知识")

    failed = await client.post(
        f"{REVIEWS}/{review_id}/approve",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={},
    )
    assert failed.status_code == 200
    assert failed.json()["status"] == "approval_failed"
    assert failed.json()["index_status"] == "index_failed"
    asset_id = failed.json()["target_asset_id"]
    asset = await db_session.get(KnowledgeAsset, uuid.UUID(asset_id))
    assert asset is not None and asset.asset_status == "processing"
    hidden = await client.get(f"{KNOWLEDGE}/{asset_id}", headers=_hdr(USER_CONSULTANT))
    assert hidden.status_code == 404
    assert "SECRET-LIKE" not in failed.text

    succeeding = _ApprovalWeKnora(fail=False)
    app.dependency_overrides[get_weknora_client] = lambda: succeeding
    retried = await client.post(
        f"{REVIEWS}/{review_id}/approve",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={},
    )
    assert retried.status_code == 200
    assert retried.json()["status"] == "approved"
    assert retried.json()["target_asset_id"] == asset_id
    assert succeeding.upload_count == 1


async def test_approval_revalidates_canonical_markdown_before_materialization(
    client, db_session, monkeypatch
):
    monkeypatch.setattr("app.services.ingest.weknora_enabled", lambda: True)
    fake = _ApprovalWeKnora(fail=False)
    app.dependency_overrides[get_weknora_client] = lambda: fake
    task_id, review_id = await _submit(client, title="Markdown 完整性审批保护")

    derivative = await db_session.scalar(
        select(IngestTaskDerivative).where(
            IngestTaskDerivative.ingest_task_id == uuid.UUID(task_id),
            IngestTaskDerivative.derivative_type == "canonical_markdown",
        )
    )
    assert derivative is not None
    derivative.content_hash = "0" * 64
    await db_session.commit()

    response = await client.post(
        f"{REVIEWS}/{review_id}/approve",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["denied_reason"] == "canonical_markdown_not_ready"
    assert fake.upload_count == 0
    db_session.expire_all()
    review = await db_session.get(ReviewTask, uuid.UUID(review_id))
    task = await db_session.get(IngestTask, uuid.UUID(task_id))
    assert review is not None and review.status == "approval_failed"
    assert review.target_asset_id is None
    assert task is not None and task.status == "waiting_review"
    assert task.result_asset_id is None
    asset_count = await db_session.scalar(
        select(func.count())
        .select_from(KnowledgeAsset)
        .where(KnowledgeAsset.title == "Markdown 完整性审批保护")
    )
    assert asset_count == 0

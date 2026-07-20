"""PBC-83 个人知识分页读模型、审核状态、编辑与删除保护。"""

from __future__ import annotations

from sqlalchemy import select

from app.models.audit import AuditEvent
from app.models.identity import ProjectMember
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetTag
from app.models.review import PersonalKnowledgeSubmission, ReviewTask
from app.seed.dev_seed import (
    PROJECT_ALPHA,
    PROJECT_BETA,
    USER_ADMIN_ONLY,
    USER_CONSULTANT,
    USER_PROJECT_MANAGER,
)
from app.services import knowledge as knowledge_service

MY = "/api/v1/my/knowledge"


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


async def _asset(db_session, title: str, *, zone="asset", asset_type="methodology"):
    asset = KnowledgeAsset(
        title=title,
        scope="personal",
        zone=zone,
        asset_type=asset_type,
        owner_user_id=USER_CONSULTANT,
        visibility="confidential",
        confidentiality_level="L2",
        ai_access_level="A2",
        asset_status="active",
    )
    asset.tags.append(KnowledgeAssetTag(tag_name="PBC83安全标签"))
    db_session.add(asset)
    await db_session.commit()
    return asset.id


async def _submit(client, asset_id):
    response = await client.post(
        f"{MY}/{asset_id}/submit-to-project",
        headers=_hdr(USER_CONSULTANT),
        json={"target_project_id": str(PROJECT_ALPHA)},
    )
    assert response.status_code == 200, response.text
    return response.json()["review_task_id"]


async def test_owner_search_filter_sort_and_pagination(client, db_session):
    await _asset(db_session, "PBC83 Alpha", asset_type="methodology")
    await _asset(db_session, "PBC83 Beta", asset_type="template")
    await _asset(db_session, "PBC83 Gamma", asset_type="methodology")

    first = await client.get(
        MY,
        headers=_hdr(USER_CONSULTANT),
        params={
            "keyword": "PBC83",
            "asset_type": "methodology",
            "sort_by": "title",
            "sort_direction": "asc",
            "page": 1,
            "page_size": 1,
        },
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["total"] == 2
    assert body["page"] == 1 and body["page_size"] == 1 and body["has_next"] is True
    assert body["items"][0]["title"] == "PBC83 Alpha"
    assert set(body["summary"]) == {
        "total_assets",
        "awaiting_confirmation",
        "pending_project_review",
        "active_in_project",
        "created_this_month",
    }

    second = await client.get(
        MY,
        headers=_hdr(USER_CONSULTANT),
        params={
            "keyword": "PBC83",
            "asset_type": "methodology",
            "sort_by": "title",
            "sort_direction": "asc",
            "page": 2,
            "page_size": 1,
        },
    )
    assert second.json()["items"][0]["title"] == "PBC83 Gamma"
    by_tag = await client.get(MY, headers=_hdr(USER_CONSULTANT), params={"keyword": "安全标签"})
    assert by_tag.status_code == 200 and by_tag.json()["total"] >= 3


async def test_query_validation_and_admin_isolation(client):
    assert (
        await client.get(MY, headers=_hdr(USER_CONSULTANT), params={"keyword": "   "})
    ).status_code == 422
    assert (
        await client.get(MY, headers=_hdr(USER_CONSULTANT), params={"page": 0})
    ).status_code == 422
    assert (
        await client.get(MY, headers=_hdr(USER_CONSULTANT), params={"page_size": 101})
    ).status_code == 422
    assert (
        await client.get(MY, headers=_hdr(USER_CONSULTANT), params={"asset_type": "bad"})
    ).status_code == 422
    assert (
        await client.get(
            MY,
            headers=_hdr(USER_CONSULTANT),
            params={"personal_state": "evidence_registered"},
        )
    ).status_code == 422
    denied = await client.get(MY, headers=_hdr(USER_ADMIN_ONLY))
    assert denied.status_code == 403
    assert "summary" not in denied.json()


async def test_real_personal_states_follow_review_and_project_copy(client, db_session):
    material_id = await _asset(db_session, "PBC83State Material", zone="material")
    ready_id = await _asset(db_session, "PBC83State Ready")
    pending_id = await _asset(db_session, "PBC83State Pending")
    rejected_id = await _asset(db_session, "PBC83State Rejected")
    approved_id = await _asset(db_session, "PBC83State Approved")

    await _submit(client, pending_id)
    rejected_review = await _submit(client, rejected_id)
    rejected = await client.post(
        f"/api/v1/reviews/{rejected_review}/reject",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={"review_comment": "资料需补充"},
    )
    assert rejected.status_code == 200, rejected.text
    approved_review = await _submit(client, approved_id)
    approved = await client.post(
        f"/api/v1/reviews/{approved_review}/approve",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={"review_comment": "同意进入项目"},
    )
    assert approved.status_code == 200, approved.text

    evidence = await client.post(
        f"{MY}/{ready_id}/validation-evidence",
        headers=_hdr(USER_CONSULTANT),
        json={
            "target_project_id": str(PROJECT_ALPHA),
            "evidence_type": "internal_sharing",
            "evidence_category": "meeting_minutes",
            "description": "只用于测试聚合，响应不得回显正文",
        },
    )
    assert evidence.status_code == 200

    response = await client.get(
        MY, headers=_hdr(USER_CONSULTANT), params={"keyword": "PBC83State", "page_size": 100}
    )
    assert response.status_code == 200, response.text
    items = {row["id"]: row for row in response.json()["items"]}
    assert items[str(material_id)]["personal_state"] == "awaiting_confirmation"
    assert items[str(ready_id)]["personal_state"] == "ready_to_submit"
    assert items[str(ready_id)]["evidence_summary"]["registered_count"] == 1
    assert items[str(pending_id)]["personal_state"] == "pending_project_review"
    assert items[str(rejected_id)]["personal_state"] == "project_rejected"
    assert items[str(approved_id)]["personal_state"] == "active_in_project"
    assert items[str(approved_id)]["project_submission"]["target_project_name"]
    body_text = response.text.lower()
    for forbidden in (
        "review_task_id",
        "submission_id",
        "target_project_id",
        "evidence_id",
        "storage_ref",
        "weknora_kb_id",
        "weknora_doc_id",
        "只用于测试聚合",
    ):
        assert forbidden not in body_text

    rejected_submission = (
        await db_session.execute(
            select(PersonalKnowledgeSubmission).where(
                PersonalKnowledgeSubmission.source_asset_id == rejected_id,
                PersonalKnowledgeSubmission.submission_type == "submit_to_project",
            )
        )
    ).scalar_one()
    assert rejected_submission.status == "rejected"
    project_copy = (
        await db_session.execute(
            select(KnowledgeAsset).where(
                KnowledgeAsset.source_asset_id == approved_id,
                KnowledgeAsset.scope == "project",
                KnowledgeAsset.project_id == PROJECT_ALPHA,
            )
        )
    ).scalar_one()
    assert project_copy.asset_status == "active"


async def test_owner_metadata_edit_and_project_lock(client, db_session):
    editable_id = await _asset(db_session, "PBC83 Edit Me")
    changed = await client.patch(
        f"{MY}/{editable_id}",
        headers=_hdr(USER_CONSULTANT),
        json={"title": "PBC83 Edited", "asset_type": "insight", "tags": ["方法", "方法"]},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["title"] == "PBC83 Edited"
    assert changed.json()["asset_type"] == "insight"
    assert changed.json()["tags"] == ["方法"]
    assert (
        await client.patch(
            f"{MY}/{editable_id}", headers=_hdr(USER_PROJECT_MANAGER), json={"title": "越权"}
        )
    ).status_code == 404
    forbidden_field = await client.patch(
        f"{MY}/{editable_id}",
        headers=_hdr(USER_CONSULTANT),
        json={"storage_ref": "SECRET-LIKE"},
    )
    assert forbidden_field.status_code == 422

    locked_id = await _asset(db_session, "PBC83 Locked")
    await _submit(client, locked_id)
    locked_edit = await client.patch(
        f"{MY}/{locked_id}", headers=_hdr(USER_CONSULTANT), json={"title": "不可修改"}
    )
    assert locked_edit.status_code == 409
    assert locked_edit.json()["detail"]["denied_reason"] == "personal_asset_project_locked"
    locked_delete = await client.post(
        f"/api/v1/knowledge/{locked_id}/delete",
        headers=_hdr(USER_CONSULTANT),
        json={"reason": "误上传"},
    )
    assert locked_delete.status_code == 409

    audit = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.action == "knowledge.asset_metadata_updated",
                AuditEvent.target_id == editable_id,
            )
        )
    ).scalar_one()
    audit_text = f"{audit.before_snapshot}{audit.after_snapshot}{audit.extra}".lower()
    assert "storage_ref" not in audit_text and "secret-like" not in audit_text


async def test_personal_state_filter_uses_projected_status(client, db_session):
    asset_id = await _asset(db_session, "PBC83 Filter Pending")
    await _submit(client, asset_id)
    response = await client.get(
        MY,
        headers=_hdr(USER_CONSULTANT),
        params={"personal_state": "pending_project_review", "keyword": "PBC83 Filter"},
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["personal_state_label"] == "待项目经理审批"
    task = (
        await db_session.execute(select(ReviewTask).where(ReviewTask.target_asset_id == asset_id))
    ).scalar_one()
    assert task.status == "pending_reviewer"


async def test_active_project_copy_wins_over_later_cross_project_rejection(client, db_session):
    beta_consultant = (
        await db_session.execute(
            select(ProjectMember).where(
                ProjectMember.user_id == USER_CONSULTANT,
                ProjectMember.project_id == PROJECT_BETA,
            )
        )
    ).scalar_one()
    beta_consultant.status = "active"
    db_session.add(
        ProjectMember(
            user_id=USER_PROJECT_MANAGER,
            project_id=PROJECT_BETA,
            project_role="project_manager",
            status="active",
        )
    )
    await db_session.commit()

    asset_id = await _asset(db_session, "PBC83 Cross Project")
    approved_review = await _submit(client, asset_id)
    approved = await client.post(
        f"/api/v1/reviews/{approved_review}/approve",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={"review_comment": "同意进入 Alpha 项目"},
    )
    assert approved.status_code == 200, approved.text

    beta_submission = await client.post(
        f"{MY}/{asset_id}/submit-to-project",
        headers=_hdr(USER_CONSULTANT),
        json={"target_project_id": str(PROJECT_BETA)},
    )
    assert beta_submission.status_code == 200, beta_submission.text
    rejected = await client.post(
        f"/api/v1/reviews/{beta_submission.json()['review_task_id']}/reject",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={"review_comment": "暂不进入 Beta 项目"},
    )
    assert rejected.status_code == 200, rejected.text

    response = await client.get(
        MY,
        headers=_hdr(USER_CONSULTANT),
        params={"keyword": "PBC83 Cross Project"},
    )
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["personal_state"] == "active_in_project"
    assert item["project_submission"]["status"] == "rejected"
    assert item["project_submission"]["target_project_name"] == "Beta 项目"
    active_filter = await client.get(
        MY,
        headers=_hdr(USER_CONSULTANT),
        params={
            "keyword": "PBC83 Cross Project",
            "personal_state": "active_in_project",
        },
    )
    rejected_filter = await client.get(
        MY,
        headers=_hdr(USER_CONSULTANT),
        params={
            "keyword": "PBC83 Cross Project",
            "personal_state": "project_rejected",
        },
    )
    assert active_filter.json()["total"] == 1
    assert rejected_filter.json()["total"] == 0
    assert active_filter.json()["summary"]["active_in_project"] >= 1
    assert (
        await client.patch(
            f"{MY}/{asset_id}",
            headers=_hdr(USER_CONSULTANT),
            json={"title": "不得因后续驳回而解锁"},
        )
    ).status_code == 409


async def test_large_personal_collection_only_projects_the_requested_page(
    client, db_session, monkeypatch
):
    assets = [
        KnowledgeAsset(
            title=f"PBC83 Bounded {index:03d}",
            scope="personal",
            zone="asset",
            asset_type="methodology",
            owner_user_id=USER_CONSULTANT,
            visibility="confidential",
            confidentiality_level="L2",
            ai_access_level="A2",
            asset_status="active",
        )
        for index in range(125)
    ]
    db_session.add_all(assets)
    await db_session.commit()

    projected_batch_sizes: list[int] = []
    original_projection = knowledge_service._personal_projection

    async def tracked_projection(session, page_assets):
        projected_batch_sizes.append(len(page_assets))
        return await original_projection(session, page_assets)

    monkeypatch.setattr(knowledge_service, "_personal_projection", tracked_projection)
    response = await client.get(
        MY,
        headers=_hdr(USER_CONSULTANT),
        params={
            "keyword": "PBC83 Bounded",
            "sort_by": "title",
            "sort_direction": "asc",
            "page": 7,
            "page_size": 5,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 125
    assert len(body["items"]) == 5
    assert body["items"][0]["title"] == "PBC83 Bounded 030"
    assert projected_batch_sizes == [5]

"""Deep links retain authorization and select records before recent-list limits."""

import uuid
from datetime import timedelta

from sqlalchemy import select

from app.db.utils import utc_now
from app.models.identity import ProjectMember
from app.models.indexing_job import IndexingOperationJob
from app.models.ingest import IngestTask
from app.models.knowledge import KnowledgeAsset
from app.models.original_access import OriginalAccessRequest
from app.seed.dev_seed import PROJECT_ALPHA, USER_ADMIN_ONLY, USER_CONSULTANT, USER_PROJECT_MANAGER


def headers(user):
    return {"X-Dev-User-Id": str(user)}


async def test_upload_target_finds_older_record_without_disclosing_another_owners(
    client, db_session
):
    now = utc_now()
    old = IngestTask(
        source="path_b_upload",
        source_file_ref="private/old-file",
        source_file_name="Old.txt",
        status="completed",
        created_by=USER_CONSULTANT,
        created_at=now - timedelta(days=10),
        target_scope="personal",
    )
    other = IngestTask(
        source="path_b_upload",
        source_file_ref="private/other-file",
        source_file_name="Other.txt",
        status="completed",
        created_by=USER_PROJECT_MANAGER,
        target_scope="personal",
    )
    db_session.add_all(
        [old, other]
        + [
            IngestTask(
                source="path_b_upload",
                source_file_ref=f"private/new-{index}",
                source_file_name=f"Recent-{index}.txt",
                status="completed",
                created_by=USER_CONSULTANT,
                target_scope="personal",
                created_at=now,
            )
            for index in range(501)
        ]
    )
    await db_session.commit()
    response = await client.get(
        f"/api/v1/ingest/my-uploads?task_id={old.id}", headers=headers(USER_CONSULTANT)
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["task_id"] == str(old.id)
    assert "private/" not in response.text
    for unavailable in [other.id, uuid.uuid4()]:
        result = await client.get(
            f"/api/v1/ingest/my-uploads?task_id={unavailable}", headers=headers(USER_CONSULTANT)
        )
        assert result.status_code == 200
        assert result.json() == {"items": [], "total": 0}
    denied = await client.get(
        f"/api/v1/ingest/my-uploads?task_id={old.id}", headers=headers(USER_ADMIN_ONLY)
    )
    assert denied.status_code == 403


async def test_operation_target_is_found_before_recent_limit_and_keeps_ops_guard(
    client, db_session, monkeypatch
):
    from app.services import indexing_ops

    monkeypatch.setattr(indexing_ops, "_RECENT_JOBS_LIMIT", 1)
    old = IndexingOperationJob(
        operation_type="retry_index",
        status="completed",
        requested_by_user_id=USER_ADMIN_ONLY,
        requested_at=utc_now() - timedelta(days=10),
    )
    recent = IndexingOperationJob(
        operation_type="retry_index", status="completed", requested_by_user_id=USER_ADMIN_ONLY
    )
    db_session.add_all([old, recent])
    await db_session.commit()
    result = await client.get(
        f"/admin/ops/indexing/jobs?job_id={old.id}", headers=headers(USER_ADMIN_ONLY)
    )
    assert result.status_code == 200
    assert [row["job_id"] for row in result.json()["items"]] == [str(old.id)]
    denied = await client.get(
        f"/admin/ops/indexing/jobs?job_id={old.id}", headers=headers(USER_CONSULTANT)
    )
    assert denied.status_code == 403
    missing = await client.get(
        f"/admin/ops/indexing/jobs?job_id={uuid.uuid4()}", headers=headers(USER_ADMIN_ONLY)
    )
    assert missing.status_code == 200
    assert missing.json() == {"items": [], "total": 0}


async def test_decided_request_deep_link_keeps_live_requester_and_approver_boundaries(
    client, db_session
):
    asset = KnowledgeAsset(
        title="Synthetic approval target",
        scope="project",
        zone="asset",
        asset_type="case",
        owner_user_id=USER_PROJECT_MANAGER,
        project_id=PROJECT_ALPHA,
        confidentiality_level="L3",
        asset_status="active",
    )
    db_session.add(asset)
    await db_session.flush()
    request = OriginalAccessRequest(
        asset_id=asset.id,
        project_id=PROJECT_ALPHA,
        requester_user_id=USER_CONSULTANT,
        status="approved",
        reviewer_user_id=USER_PROJECT_MANAGER,
        reviewed_at=utc_now(),
    )
    db_session.add(request)
    await db_session.commit()
    path = f"/api/v1/original-access/requests/{request.id}"
    for user in [USER_CONSULTANT, USER_PROJECT_MANAGER]:
        response = await client.get(path, headers=headers(user))
        assert response.status_code == 200
        assert response.json()["request_id"] == str(request.id)
        assert response.json()["status"] == "approved"
    inbox = await client.get(
        "/api/v1/original-access/requests?box=inbox", headers=headers(USER_PROJECT_MANAGER)
    )
    assert request.id not in {uuid.UUID(item["request_id"]) for item in inbox.json()["items"]}
    membership = await db_session.scalar(
        select(ProjectMember).where(
            ProjectMember.user_id == USER_PROJECT_MANAGER,
            ProjectMember.project_id == PROJECT_ALPHA,
        )
    )
    membership.project_role = "consultant"
    await db_session.commit()
    denied = await client.get(path, headers=headers(USER_PROJECT_MANAGER))
    assert denied.status_code == 404
    assert asset.title not in denied.text
    membership.status = "inactive"
    asset.confidentiality_level = "L5"
    requester_membership = await db_session.scalar(
        select(ProjectMember).where(
            ProjectMember.user_id == USER_CONSULTANT,
            ProjectMember.project_id == PROJECT_ALPHA,
        )
    )
    requester_membership.status = "inactive"
    await db_session.commit()
    assert (await client.get(path, headers=headers(USER_PROJECT_MANAGER))).status_code == 404
    assert (await client.get(path, headers=headers(USER_CONSULTANT))).status_code == 404
    assert (await client.get(path, headers=headers(USER_ADMIN_ONLY))).status_code == 403
    assert (
        await client.get(
            f"/api/v1/original-access/requests/{uuid.uuid4()}", headers=headers(USER_CONSULTANT)
        )
    ).status_code == 404

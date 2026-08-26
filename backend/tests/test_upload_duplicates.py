from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.models.audit import AuditEvent
from app.models.ingest import IngestTask, UploadSessionItem
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.schemas.enums import AuditAction, IngestSource, IngestStatus
from app.schemas.permission import CallerContext
from app.seed.dev_seed import PROJECT_ALPHA, PROJECT_BETA, USER_CONSULTANT, USER_PROJECT_MANAGER
from app.services.upload_duplicates import read_duplicate


def _headers(user_id: uuid.UUID = USER_CONSULTANT) -> dict[str, str]:
    return {"X-Dev-User-Id": str(user_id)}


def _confirmation() -> dict:
    return {
        "title": "重复识别测试资料",
        "summary": "用于验证服务端哈希查重与明确处理决定。",
        "tags": [],
        "target_scope": "personal",
        "target_zone": "material",
        "confidentiality_level": "L2",
        "directory_key": "personal.learning_notes",
    }


async def _upload(client, name: str, content: bytes, user_id: uuid.UUID = USER_CONSULTANT) -> str:
    response = await client.post(
        "/api/v1/ingest/upload",
        headers=_headers(user_id),
        data={"target_scope": "personal"},
        files={"file": (name, content, "text/plain")},
    )
    assert response.status_code == 200
    return response.json()["ingest_task_id"]


async def test_exact_content_requires_explicit_decision_and_skip_is_idempotent(client, db_session):
    content = "去重测试的唯一正文。".encode()
    first = await _upload(client, "first.txt", content)
    confirmed = await client.post(
        f"/api/v1/ingest/{first}/confirm", headers=_headers(), json=_confirmation()
    )
    assert confirmed.status_code == 200

    second = await _upload(client, "second.txt", content)
    preview = await client.post(
        f"/api/v1/ingest/{second}/naming-preview",
        headers=_headers(),
        json={"target_scope": "personal", "confidentiality_level": "L2"},
    )
    assert preview.status_code == 200
    duplicate = preview.json()["duplicate"]
    assert duplicate["duplicate_state"] == "exact_content"
    assert duplicate["match_type"] == "exact_content"
    assert duplicate["preferred_candidate"]["title"] == "重复识别测试资料"
    assert "hash" not in preview.text.lower()

    blocked = await client.post(
        f"/api/v1/ingest/{second}/confirm", headers=_headers(), json=_confirmation()
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["denied_reason"] == "duplicate_decision_required"

    decision = {
        "action": "skip",
        "target_scope": "personal",
        "target_project_id": None,
    }
    first_skip = await client.post(
        f"/api/v1/ingest/{second}/duplicate-decision", headers=_headers(), json=decision
    )
    repeated_skip = await client.post(
        f"/api/v1/ingest/{second}/duplicate-decision", headers=_headers(), json=decision
    )
    assert first_skip.json()["status"] == "duplicate_skipped"
    assert repeated_skip.json() == first_skip.json()
    task = await db_session.get(IngestTask, uuid.UUID(second))
    assert task is not None and task.result_asset_id is None
    audit_count = await db_session.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.target_id == uuid.UUID(second),
            AuditEvent.action == AuditAction.ingest_duplicate_skipped.value,
        )
    )
    assert audit_count == 1

    history = await client.get("/api/v1/ingest/my-uploads", headers=_headers())
    by_id = {item["task_id"]: item for item in history.json()["items"]}
    assert by_id[second]["final_status"] == "duplicate_skipped"
    assert by_id[second]["duplicate_result"] == "skipped"


async def test_same_batch_keep_switch_is_atomic_and_survives_refresh(client, db_session):
    content = b"same batch exact bytes"
    response = await client.post(
        "/api/v1/ingest/upload-sessions",
        headers=_headers(),
        data={"target_scope": "personal"},
        files=[
            ("files", ("one.txt", content, "text/plain")),
            ("files", ("two.txt", content, "text/plain")),
            ("files", ("three.txt", b"different", "text/plain")),
        ],
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert items[0]["duplicate"]["duplicate_state"] == "same_batch"
    assert items[1]["duplicate"]["duplicate_state"] == "same_batch"
    assert (
        items[0]["duplicate"]["same_batch_group_id"] == items[1]["duplicate"]["same_batch_group_id"]
    )
    assert items[0]["duplicate"]["default_selected"] is True
    assert items[1]["duplicate"]["default_selected"] is False
    assert items[2]["duplicate"]["duplicate_state"] == "none"

    session_items = (
        (
            await db_session.execute(
                select(UploadSessionItem)
                .where(UploadSessionItem.session_id == uuid.UUID(response.json()["id"]))
                .order_by(UploadSessionItem.ordinal)
            )
        )
        .scalars()
        .all()
    )
    keep = await client.post(
        f"/api/v1/ingest/{session_items[1].ingest_task_id}/duplicate-decision",
        headers=_headers(),
        json={"action": "keep", "target_scope": "personal"},
    )
    assert keep.status_code == 200
    assert keep.json()["decision"] == "batch_keep"
    assert keep.json()["skipped_task_ids"] == [str(session_items[0].ingest_task_id)]

    recovered = await client.get(
        f"/api/v1/ingest/upload-sessions/{response.json()['id']}", headers=_headers()
    )
    recovered_items = recovered.json()["items"]
    assert recovered_items[0]["status"] == "duplicate_skipped"
    assert recovered_items[0]["duplicate"]["default_selected"] is False
    assert recovered_items[0]["duplicate"]["decision"] == "skip"
    assert recovered_items[1]["status"] == "awaiting_confirmation"
    assert recovered_items[1]["duplicate"]["default_selected"] is True
    assert recovered_items[1]["duplicate"]["decision"] == "batch_keep"
    assert (
        recovered_items[1]["duplicate"]["same_batch_group_id"]
        == items[1]["duplicate"]["same_batch_group_id"]
    )

    repeated = await client.post(
        f"/api/v1/ingest/{session_items[1].ingest_task_id}/duplicate-decision",
        headers=_headers(),
        json={"action": "keep", "target_scope": "personal"},
    )
    assert repeated.status_code == 200
    audit_count = await db_session.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(
            AuditEvent.target_id == session_items[1].ingest_task_id,
            AuditEvent.action == AuditAction.ingest_duplicate_batch_kept.value,
        )
    )
    assert audit_count == 1


async def test_restricted_match_exposes_no_asset_facts(db_session):
    content_hash = "a" * 64
    asset = KnowledgeAsset(
        title="不得泄露的公司绝密资料",
        scope="company",
        zone="material",
        asset_type="document",
        owner_user_id=USER_CONSULTANT,
        visibility="company_wide",
        confidentiality_level="L5",
        ai_access_level="A1",
        asset_status="active",
    )
    db_session.add(asset)
    await db_session.flush()
    version = KnowledgeAssetVersion(
        asset_id=asset.id,
        version_no="V1",
        version_status="active",
        file_hash=content_hash,
        created_by=USER_CONSULTANT,
    )
    task = IngestTask(
        source=IngestSource.path_b_upload.value,
        source_file_ref="internal://restricted-current",
        source_file_name="current.txt",
        source_file_hash=content_hash,
        status=IngestStatus.pending_confirmation.value,
        target_scope="company",
        created_by=USER_CONSULTANT,
    )
    db_session.add_all([version, task])
    await db_session.commit()
    caller = CallerContext(
        user_id=USER_CONSULTANT,
        is_active=True,
        active_company_roles={"consultant"},
        active_project_ids=set(),
    )

    duplicate = await read_duplicate(db_session, caller, task, scope="company", project_id=None)

    assert duplicate.duplicate_state == "exact_content"
    assert duplicate.match_type == "restricted_match"
    assert duplicate.match_count is None
    assert duplicate.preferred_candidate is not None
    assert duplicate.preferred_candidate.model_dump(exclude={"match_type"}) == {
        "title": None,
        "file_name": None,
        "file_size": None,
        "scope": None,
        "scope_label": None,
        "directory_key": None,
        "subject": None,
        "formed_on": None,
        "version": None,
        "asset_status": None,
        "ingested_at": None,
        "safe_summary": None,
        "asset_id": None,
        "can_view_detail": False,
        "can_view_original": False,
        "same_batch_ordinal": None,
    }


async def test_project_duplicate_lookup_is_isolated_and_metadata_match_is_non_blocking(db_session):
    asset = KnowledgeAsset(
        title="另一个项目的资料",
        scope="project",
        project_id=PROJECT_BETA,
        zone="material",
        asset_type="document",
        owner_user_id=USER_PROJECT_MANAGER,
        visibility="project_wide",
        confidentiality_level="L2",
        ai_access_level="A1",
        asset_status="active",
    )
    db_session.add(asset)
    await db_session.flush()
    metadata = {
        "category_id": "delivery",
        "subject": "范围隔离",
        "formed_on": "2026-08-26",
        "version": "V1",
    }
    db_session.add(
        KnowledgeAssetVersion(
            asset_id=asset.id,
            version_no="V1",
            version_status="active",
            file_hash="b" * 64,
            naming_metadata=metadata,
            created_by=USER_PROJECT_MANAGER,
        )
    )
    task = IngestTask(
        source=IngestSource.path_b_upload.value,
        source_file_ref="internal://project-alpha-current",
        source_file_name="current.txt",
        source_file_hash="b" * 64,
        status=IngestStatus.pending_confirmation.value,
        target_scope="project",
        target_project_id=PROJECT_ALPHA,
        created_by=USER_PROJECT_MANAGER,
    )
    db_session.add(task)
    await db_session.commit()
    caller = CallerContext(
        user_id=USER_PROJECT_MANAGER,
        is_active=True,
        active_company_roles=set(),
        active_project_ids={PROJECT_ALPHA, PROJECT_BETA},
    )

    isolated = await read_duplicate(
        db_session,
        caller,
        task,
        scope="project",
        project_id=PROJECT_ALPHA,
        metadata=metadata,
    )
    assert isolated.duplicate_state == "none"

    asset.project_id = PROJECT_ALPHA
    task.source_file_hash = "c" * 64
    await db_session.commit()
    suspected = await read_duplicate(
        db_session,
        caller,
        task,
        scope="project",
        project_id=PROJECT_ALPHA,
        metadata=metadata,
    )
    assert suspected.duplicate_state == "suspected_metadata"
    assert suspected.default_selected is True


async def test_independent_decision_creates_once_and_history_excludes_other_users(
    client, db_session
):
    content = "独立入库必须显式决定。".encode()
    first = await _upload(client, "original.txt", content)
    assert (
        await client.post(
            f"/api/v1/ingest/{first}/confirm", headers=_headers(), json=_confirmation()
        )
    ).status_code == 200
    second = await _upload(client, "independent.txt", content)
    decision = await client.post(
        f"/api/v1/ingest/{second}/duplicate-decision",
        headers=_headers(),
        json={"action": "independent", "target_scope": "personal"},
    )
    assert decision.status_code == 200

    confirmed = await client.post(
        f"/api/v1/ingest/{second}/confirm", headers=_headers(), json=_confirmation()
    )
    repeated = await client.post(
        f"/api/v1/ingest/{second}/confirm", headers=_headers(), json=_confirmation()
    )
    assert confirmed.status_code == 200
    assert repeated.status_code == 409
    asset_count = await db_session.scalar(
        select(func.count())
        .select_from(KnowledgeAsset)
        .where(
            KnowledgeAsset.owner_user_id == USER_CONSULTANT,
            KnowledgeAsset.title == "重复识别测试资料",
        )
    )
    assert asset_count == 2

    await _upload(client, "other-user.txt", b"other", user_id=USER_PROJECT_MANAGER)
    history = await client.get("/api/v1/ingest/my-uploads", headers=_headers())
    assert all(item["source_file_name"] != "other-user.txt" for item in history.json()["items"])

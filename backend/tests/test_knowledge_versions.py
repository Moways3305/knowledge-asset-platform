"""Replacement upload provenance, safe history and repeated updates."""

import uuid

import pytest
from sqlalchemy import select
from test_knowledge_review import headers, state, verify

from app.models.ingest import IngestTask
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetSummary, KnowledgeAssetVersion
from app.seed.dev_seed import (
    KA_COMPANY_L2,
    KA_PERSONAL,
    KA_PROJECT_ALPHA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
    USER_PROJECT_MANAGER,
)


async def source(db, asset_id=KA_PERSONAL, directory="personal.learning_notes"):
    asset = await db.get(KnowledgeAsset, asset_id)
    version = await db.get(KnowledgeAssetVersion, asset.current_version_id)
    version.directory_key = directory
    await db.commit()
    return asset


async def upload_update(client, asset, user=USER_CONSULTANT, version="V2"):
    return await client.post(
        "/api/v1/ingest/upload",
        headers=headers(user),
        data={
            "update_of_asset_id": str(asset.id),
            "expected_updated_at": asset.updated_at.isoformat(),
            "version_label": version,
        },
        files={
            "file": (f"notes-{version}.txt", f"新版实施方法与复盘 {version}".encode(), "text/plain")
        },
    )


@pytest.mark.parametrize("stale_baseline", [False, True])
async def test_upload_confirm_review_replace_and_history(client, db_session, stale_baseline):
    asset = await source(db_session)
    uploaded = await upload_update(client, asset)
    assert uploaded.status_code == 200, uploaded.text
    task_id = uploaded.json()["ingest_task_id"]
    task = await db_session.get(IngestTask, uuid.UUID(task_id))
    assert (
        task.update_of_asset_id == asset.id
        and task.update_of_version_id == asset.current_version_id
    )
    old = await state(client, asset.id, USER_CONSULTANT)
    assert old["freshness"] != "archived" and not old["replacement_asset_id"]
    ai = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=headers(USER_CONSULTANT))
    assert ai.status_code == 200, ai.text
    assert ai.json()["update_context"]["version"] == "V2"
    body = {
        "title": "新版复盘",
        "summary": "更新了实施方法",
        "target_scope": "personal",
        "target_zone": asset.zone,
        "confidentiality_level": asset.confidentiality_level,
        "directory_key": "personal.learning_notes",
    }
    invalid = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=headers(USER_CONSULTANT),
        json={**body, "directory_key": "personal.project_materials"},
    )
    assert invalid.status_code == 422
    result = await client.post(
        f"/api/v1/ingest/{task_id}/confirm", headers=headers(USER_CONSULTANT), json=body
    )
    assert result.status_code == 200, result.text
    new_id = result.json()["result_asset_id"]
    route = f"/api/v1/knowledge/{asset.id}/versions"
    history = (await client.get(route, headers=headers(USER_CONSULTANT))).json()
    assert history["current_asset_id"] == str(asset.id)
    assert history["updates"][0]["can_replace"] is False
    new_version = next(row for row in history["items"] if row["asset_id"] == new_id)
    assert new_version["version"] == "V2" and not new_version["is_current"]
    candidate_history = (
        await client.get(f"/api/v1/knowledge/{new_id}/versions", headers=headers(USER_CONSULTANT))
    ).json()
    assert candidate_history["can_update"] is False
    assert candidate_history["current_asset_id"] == str(asset.id)
    await verify(client, uuid.UUID(new_id), USER_CONSULTANT)
    current = await state(client, uuid.UUID(new_id), USER_CONSULTANT)
    if stale_baseline:
        from app.db.utils import utc_now

        await db_session.refresh(asset)
        baseline = await db_session.get(KnowledgeAssetVersion, asset.current_version_id)
        baseline.version_status = "superseded"
        await db_session.flush()
        newer = KnowledgeAssetVersion(
            asset_id=asset.id,
            version_no="V3",
            version_status="active",
            created_by=USER_CONSULTANT,
            directory_key=baseline.directory_key,
        )
        db_session.add(newer)
        await db_session.flush()
        asset.current_version_id = newer.id
        asset.updated_at = utc_now()
        await db_session.commit()
        old = await state(client, asset.id, USER_CONSULTANT)
        history = (await client.get(route, headers=headers(USER_CONSULTANT))).json()
        assert history["updates"][0]["can_replace"] is False
    replaced = await client.post(
        f"/api/v1/knowledge/{asset.id}/trust/replacement",
        headers=headers(USER_CONSULTANT),
        json={
            "expected_updated_at": old["updated_at"],
            "expected_replacement_updated_at": current["updated_at"],
            "replacement_asset_id": new_id,
            "reason": "核对新版实施方法",
            "confirm_archive": True,
        },
    )
    if stale_baseline:
        assert replaced.status_code == 409, replaced.text
        await db_session.refresh(asset)
        assert asset.asset_status == "active"
        assert asset.replacement_asset_id is None
        assert asset.current_version_id == newer.id
        return
    assert replaced.status_code == 200, replaced.text
    history = (await client.get(route, headers=headers(USER_CONSULTANT))).json()
    assert history["current_asset_id"] == new_id
    original = next(row for row in history["items"] if row["asset_id"] == str(asset.id))
    diff = await client.get(
        route + f"/compare?left={original['version_id']}&right={new_version['version_id']}",
        headers=headers(USER_CONSULTANT),
    )
    assert diff.status_code == 200, diff.text
    assert "summary" in diff.json()["changed_fields"]
    assert "source_file_ref" not in diff.text
    # A third update may replace the current V2 without losing the V1 trail.
    second = await source(db_session, uuid.UUID(new_id))
    third_upload = await upload_update(client, second, version="V3")
    assert third_upload.status_code == 200, third_upload.text
    third_task = third_upload.json()["ingest_task_id"]
    third_result = await client.post(
        f"/api/v1/ingest/{third_task}/confirm",
        headers=headers(USER_CONSULTANT),
        json={**body, "title": "第三版复盘", "summary": "第三版实施流程"},
    )
    assert third_result.status_code == 200, third_result.text
    third_id = uuid.UUID(third_result.json()["result_asset_id"])
    third_state = await verify(client, third_id, USER_CONSULTANT)
    second_state = await state(client, second.id, USER_CONSULTANT)
    response = await client.post(
        f"/api/v1/knowledge/{second.id}/trust/replacement",
        headers=headers(USER_CONSULTANT),
        json={
            "expected_updated_at": second_state["updated_at"],
            "expected_replacement_updated_at": third_state["updated_at"],
            "replacement_asset_id": str(third_id),
            "reason": "核验第三版",
            "confirm_archive": True,
        },
    )
    assert response.status_code == 200, response.text
    old_state = await state(client, asset.id, USER_CONSULTANT)
    assert old_state["replacement_asset_id"] == str(third_id)
    timeline = (await client.get(route, headers=headers(USER_CONSULTANT))).json()
    assert timeline["current_asset_id"] == str(third_id)
    assert {item["version"] for item in timeline["items"]} == {"V1", "V2", "V3"}
    assert sum(item["is_current"] for item in timeline["items"]) == 1


async def test_stale_upload_and_same_version_do_not_create_updates(client, db_session):
    asset = await source(db_session)
    before = asset.updated_at
    asset.title = "已修改的原资料"
    from app.db.utils import utc_now

    asset.updated_at = utc_now()
    await db_session.commit()
    response = await client.post(
        "/api/v1/ingest/upload",
        headers=headers(USER_CONSULTANT),
        data={
            "update_of_asset_id": str(asset.id),
            "expected_updated_at": before.isoformat(),
            "version_label": "V2",
        },
        files={"file": ("new.txt", b"new content", "text/plain")},
    )
    assert response.status_code == 409
    assert (await upload_update(client, asset, version="V1")).status_code == 422
    assert not (
        await db_session.scalars(
            select(IngestTask).where(IngestTask.update_of_asset_id == asset.id)
        )
    ).all()


async def test_repeated_update_label_reuses_history_instead_of_creating_duplicate(
    client, db_session
):
    asset = await source(db_session)
    first = await upload_update(client, asset, version="V2")
    assert first.status_code == 200, first.text
    repeated = await upload_update(client, asset, version="V2.0")
    assert repeated.status_code == 409, repeated.text
    tasks = (
        await db_session.scalars(
            select(IngestTask).where(IngestTask.update_of_asset_id == asset.id)
        )
    ).all()
    assert len(tasks) == 1
    assert tasks[0].result_asset_id is None


async def test_update_preserves_existing_visibility_and_ai_policy(client, db_session):
    asset = await source(db_session)
    asset.visibility = "confidential"
    asset.ai_access_level = "A4"
    await db_session.commit()
    response = await upload_update(client, asset)
    assert response.status_code == 200, response.text
    task_id = response.json()["ingest_task_id"]
    confirmed = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=headers(USER_CONSULTANT),
        json={
            "title": "更新操作规范",
            "summary": "新操作摘要",
            "target_scope": "personal",
            "target_zone": asset.zone,
            "confidentiality_level": asset.confidentiality_level,
            "directory_key": "personal.learning_notes",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    updated = await db_session.get(KnowledgeAsset, uuid.UUID(confirmed.json()["result_asset_id"]))
    assert updated.visibility == asset.visibility
    assert updated.ai_access_level == "A4"


async def test_standalone_archive_history_does_not_expand_reader_permissions(client, db_session):
    asset = await db_session.get(KnowledgeAsset, KA_COMPANY_L2)
    asset.asset_status = "archived"
    await db_session.commit()
    route = f"/api/v1/knowledge/{asset.id}/versions"
    assert (await client.get(route, headers=headers(USER_CONSULTANT))).status_code == 404
    assert (await client.get(route, headers=headers(USER_BOSS))).status_code == 200


@pytest.mark.parametrize(
    "asset_id,user,directory,allowed",
    [
        (KA_PERSONAL, USER_CONSULTANT, "personal.learning_notes", True),
        (KA_PERSONAL, USER_DIRECTOR, "personal.learning_notes", False),
        (KA_COMPANY_L2, USER_BOSS, "company.introduction", True),
        (KA_COMPANY_L2, USER_DIRECTOR, "company.introduction", True),
        (KA_COMPANY_L2, USER_CONSULTANT, "company.introduction", False),
        (KA_COMPANY_L2, USER_ADMIN_ONLY, "company.introduction", False),
        (KA_PROJECT_ALPHA, USER_PROJECT_MANAGER, "project.deliverables", True),
        (KA_PROJECT_ALPHA, USER_CONSULTANT, "project.deliverables", False),
    ],
)
async def test_update_governance_matrix(client, db_session, asset_id, user, directory, allowed):
    asset = await source(db_session, asset_id, directory)
    result = await upload_update(client, asset, user)
    assert result.status_code == (200 if allowed else 404), result.text
    if not allowed:
        assert not (
            await db_session.scalars(
                select(IngestTask).where(IngestTask.update_of_asset_id == asset_id)
            )
        ).all()


async def test_history_and_comparison_do_not_cross_personal_permissions(client, db_session):
    asset = await source(db_session)
    route = f"/api/v1/knowledge/{asset.id}/versions"
    assert (await client.get(route, headers=headers(USER_DIRECTOR))).status_code == 404
    unrelated = await db_session.get(KnowledgeAsset, KA_COMPANY_L2)
    result = await client.get(
        route + f"/compare?left={asset.current_version_id}&right={unrelated.current_version_id}",
        headers=headers(USER_CONSULTANT),
    )
    assert result.status_code == 404


async def test_protected_summary_diff_never_falls_back_to_raw(client, db_session):
    asset = await source(db_session, KA_COMPANY_L2, "company.introduction")
    asset.confidentiality_level = "L3"
    rows = (
        await db_session.scalars(
            select(KnowledgeAssetSummary).where(
                KnowledgeAssetSummary.version_id == asset.current_version_id
            )
        )
    ).all()
    for row in rows:
        if row.summary_type in {"redacted_summary", "safe_summary"}:
            await db_session.delete(row)
        else:
            row.content = "不可泄露的原始客户信息"
    await db_session.commit()
    route = f"/api/v1/knowledge/{asset.id}/versions/compare?left={asset.current_version_id}&right={asset.current_version_id}"
    result = await client.get(route, headers=headers(USER_CONSULTANT))
    assert result.status_code == 200, result.text
    assert result.json()["left"]["summary"] is None
    assert "不可泄露" not in result.text


async def test_l2_comparison_uses_redacted_not_raw_summary(client, db_session):
    asset = await source(db_session, KA_COMPANY_L2, "company.introduction")
    rows = (
        await db_session.scalars(
            select(KnowledgeAssetSummary).where(
                KnowledgeAssetSummary.version_id == asset.current_version_id
            )
        )
    ).all()
    for row in rows:
        await db_session.delete(row)
    await db_session.flush()
    for kind, text in (
        ("detailed", "客户张三付款123456元"),
        ("redacted_summary", "客户[匿名]付款[金额已脱敏]"),
    ):
        db_session.add(
            KnowledgeAssetSummary(
                asset_id=asset.id,
                version_id=asset.current_version_id,
                summary_type=kind,
                content=text,
            )
        )
    await db_session.commit()
    result = await client.get(
        f"/api/v1/knowledge/{asset.id}/versions/compare"
        f"?left={asset.current_version_id}&right={asset.current_version_id}",
        headers=headers(USER_BOSS),
    )
    assert result.status_code == 200, result.text
    assert result.json()["left"]["summary"] == "客户[匿名]付款[金额已脱敏]"
    assert "张三" not in result.text and "123456" not in result.text


@pytest.mark.parametrize("change_during_copy", [False, True])
async def test_update_locks_only_after_copy_and_cleans_rejected_file(
    client, db_session, monkeypatch, change_during_copy
):
    from app.db.utils import utc_now
    from app.services import knowledge_versions

    asset = await source(db_session)
    events = []
    original_prepare = knowledge_versions.prepare_upload
    original_save = client._kap_storage.save_upload
    upload_sessions = []

    async def prepare(session, *args, **kwargs):
        upload_sessions.append(session)
        events.append("lock" if kwargs.get("lock", True) else "preflight")
        return await original_prepare(session, *args, **kwargs)

    async def save(*args, **kwargs):
        assert events == ["preflight"]
        assert not upload_sessions[0].in_transaction()
        events.append("copy")
        stored = await original_save(*args, **kwargs)
        if change_during_copy:
            asset.updated_at = utc_now()
            await db_session.commit()
        events.append("copied")
        return stored

    monkeypatch.setattr(knowledge_versions, "prepare_upload", prepare)
    monkeypatch.setattr(client._kap_storage, "save_upload", save)
    response = await upload_update(client, asset)
    assert events == ["preflight", "copy", "copied", "lock"]
    assert response.status_code == (409 if change_during_copy else 200), response.text
    if change_during_copy:
        assert not [p for p in client._kap_storage.root.rglob("*") if p.is_file()]
        assert not (
            await db_session.scalars(
                select(IngestTask).where(IngestTask.update_of_asset_id == asset.id)
            )
        ).all()

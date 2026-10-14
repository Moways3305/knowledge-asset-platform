"""Direct library creation cannot publish drafts or escape project boundaries."""

import pytest

from app.seed.dev_seed import (
    PROJECT_ALPHA,
    PROJECT_BETA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
    USER_PROJECT_MANAGER,
)


def headers(user):
    return {"X-Dev-User-Id": str(user)}


@pytest.mark.parametrize(
    "user,allowed",
    [
        (USER_BOSS, True),
        (USER_DIRECTOR, True),
        (USER_PROJECT_MANAGER, False),
        (USER_CONSULTANT, False),
        (USER_ADMIN_ONLY, False),
    ],
)
async def test_company_create_does_not_publish_draft(client, user, allowed):
    boss = headers(USER_BOSS)
    before = (await client.get("/api/v1/admin/naming-rules", headers=boss)).json()
    response = await client.post(
        "/api/v1/knowledge/directories",
        headers=headers(user),
        json={
            "scope": "company",
            "parent_key": "company.methodology",
            "display_name": "验收目录",
        },
    )
    assert response.status_code == (201 if allowed else 403), response.text
    after = (await client.get("/api/v1/admin/naming-rules", headers=boss)).json()
    assert after == before
    if allowed:
        key = response.json()["directory_key"]
        rows = (
            await client.get("/api/v1/knowledge/directories?scope=company", headers=boss)
        ).json()["items"]
        assert (
            next(row for row in rows if row["directory_key"] == key)["parent_key"]
            == "company.methodology"
        )
        options = (await client.get("/api/v1/naming-options?scope=company", headers=boss)).json()[
            "directories"
        ]
        assert any(
            row["directory_key"] == key and row["default_confidentiality"] == "L2"
            for row in options
        )


@pytest.mark.parametrize(
    "user,project,expected",
    [
        (USER_PROJECT_MANAGER, PROJECT_ALPHA, 201),
        (USER_PROJECT_MANAGER, PROJECT_BETA, 403),
        (USER_CONSULTANT, PROJECT_ALPHA, 403),
        (USER_BOSS, PROJECT_ALPHA, 403),
        (USER_ADMIN_ONLY, PROJECT_ALPHA, 403),
    ],
)
async def test_project_create_requires_this_project_manager(client, user, project, expected):
    response = await client.post(
        "/api/v1/knowledge/directories",
        headers=headers(user),
        json={
            "scope": "project",
            "project_id": str(project),
            "parent_key": "project.deliverables",
            "display_name": "验收目录",
        },
    )
    assert response.status_code == expected, response.text
    if expected != 201:
        return
    key = response.json()["directory_key"]
    for target, present in [(PROJECT_ALPHA, True), (PROJECT_BETA, False)]:
        rows = (
            await client.get(
                f"/api/v1/knowledge/directories?scope=project&project_id={target}",
                headers=headers(USER_BOSS),
            )
        ).json()["items"]
        assert any(row["directory_key"] == key for row in rows) == present


async def test_duplicates_and_fourth_level_are_rejected(client):
    body = {"scope": "company", "parent_key": "company.methodology", "display_name": "验收目录"}
    created = await client.post(
        "/api/v1/knowledge/directories", headers=headers(USER_BOSS), json=body
    )
    assert created.status_code == 201
    for invalid, status in [
        (body, 409),
        ({**body, "parent_key": created.json()["directory_key"], "display_name": "四级"}, 422),
        ({**body, "parent_key": "project.deliverables"}, 422),
        ({**body, "display_name": "../越界"}, 422),
    ]:
        response = await client.post(
            "/api/v1/knowledge/directories", headers=headers(USER_BOSS), json=invalid
        )
        assert response.status_code == status, response.text
        if status == 409:
            assert response.json()["detail"] == {
                "denied_reason": "directory_duplicate",
                "message": "当前分类下已存在同名目录",
            }
        elif invalid["parent_key"] != body["parent_key"]:
            assert response.json()["detail"]["denied_reason"] == "directory_parent_invalid"


async def test_project_directory_is_usable_only_in_its_project(client, db_session):
    from fastapi import HTTPException

    from app.models.identity import Project
    from app.services.directories import default_directory_config, display_path, validate_directory

    await client.get("/api/v1/admin/naming-rules", headers=headers(USER_BOSS))
    project = await db_session.get(Project, PROJECT_ALPHA)
    project.project_code = "ALPHA"
    project.project_code_active = True
    await db_session.commit()
    created = await client.post(
        "/api/v1/knowledge/directories",
        headers=headers(USER_PROJECT_MANAGER),
        json={
            "scope": "project",
            "project_id": str(PROJECT_ALPHA),
            "parent_key": "project.deliverables",
            "display_name": "验收报告",
        },
    )
    assert created.status_code == 201, created.text
    key = created.json()["directory_key"]
    # Naming preview passes an immutable policy snapshot, not a freshly loaded list.
    _, item = await validate_directory(
        db_session,
        directory_key=key,
        scope="project",
        project_id=PROJECT_ALPHA,
        published=(1, default_directory_config()),
    )
    assert item["default_confidentiality"] == "L2"
    with pytest.raises(HTTPException) as error:
        await validate_directory(
            db_session, directory_key=key, scope="project", project_id=PROJECT_BETA
        )
    assert error.value.status_code == 422
    path = await display_path(db_session, key, PROJECT_ALPHA)
    assert "03 交付成果 / 验收报告" in path
    options = await client.get(
        f"/api/v1/naming-options?scope=project&project_id={PROJECT_ALPHA}",
        headers=headers(USER_PROJECT_MANAGER),
    )
    assert options.status_code == 200, options.text
    assert any(row["directory_key"] == key for row in options.json()["directories"])


async def test_global_publish_cannot_disable_parent_of_live_child(client):
    boss = headers(USER_BOSS)
    center = (await client.get("/api/v1/admin/naming-rules", headers=boss)).json()
    created = await client.post(
        "/api/v1/knowledge/directories",
        headers=boss,
        json={
            "scope": "company",
            "parent_key": "company.methodology",
            "display_name": "验收报告",
        },
    )
    assert created.status_code == 201
    rows = center["draft"]["config"]["directories"]
    next(row for row in rows if row["directory_key"] == "company.methodology")["enabled"] = False
    saved = await client.put(
        "/api/v1/admin/naming-rules/draft",
        headers=boss,
        json={
            "expected_base_version": center["published"]["version"],
            "directories": rows,
        },
    )
    assert saved.status_code == 200, saved.text
    published = await client.post(
        "/api/v1/admin/naming-rules/publish",
        headers=boss,
        json={
            "expected_base_version": center["published"]["version"],
        },
    )
    assert published.status_code == 409, published.text


async def test_inactive_caller_cannot_create_and_no_directory_is_written(db_session):
    from fastapi import HTTPException
    from sqlalchemy import select

    from app.models.knowledge_directory import KnowledgeDirectory
    from app.schemas.knowledge_directory import DirectoryCreateRequest
    from app.schemas.permission import CallerContext
    from app.services.knowledge_directories import create_directory

    caller = CallerContext(
        user_id=USER_BOSS, is_active=False, active_company_roles={"boss"}, active_project_ids=set()
    )
    with pytest.raises(HTTPException) as error:
        await create_directory(
            db_session,
            caller,
            DirectoryCreateRequest(
                scope="company", parent_key="company.methodology", display_name="验收报告"
            ),
            "test",
        )
    assert error.value.status_code == 403
    assert (await db_session.execute(select(KnowledgeDirectory))).scalars().all() == []


@pytest.mark.parametrize(
    "scope,user,parent",
    [
        ("company", USER_BOSS, "company.methodology"),
        (
            "project",
            USER_PROJECT_MANAGER,
            "project.deliverables",
        ),
    ],
)
async def test_created_directory_upload_confirm_and_metadata_edit(
    client, db_session, scope, user, parent
):
    import uuid

    from sqlalchemy import select

    from app.models.identity import Project
    from app.models.knowledge import KnowledgeAsset, KnowledgeAssetFileObject, KnowledgeAssetVersion

    await client.get("/api/v1/admin/naming-rules", headers=headers(USER_BOSS))
    if scope == "project":
        project = await db_session.get(Project, PROJECT_ALPHA)
        project.project_code = "ALPHA"
        project.project_code_active = True
        await db_session.commit()
    created = await client.post(
        "/api/v1/knowledge/directories",
        headers=headers(user),
        json={
            "scope": scope,
            "project_id": str(PROJECT_ALPHA) if scope == "project" else None,
            "parent_key": parent,
            "display_name": "验收操作模板",
        },
    )
    assert created.status_code == 201, created.text
    key = created.json()["directory_key"]
    upload = await client.post(
        "/api/v1/ingest/upload",
        headers=headers(user),
        files={
            "file": (
                "验收目录流程.txt",
                "验收测试：这是虚构的模板资料，不是正式制度。".encode(),
                "text/plain",
            ),
        },
    )
    assert upload.status_code == 200, upload.text
    task_id = upload.json()["ingest_task_id"]
    body = {
        "target_scope": scope,
        "target_project_id": str(PROJECT_ALPHA) if scope == "project" else None,
        "confidentiality_level": "L2",
        "target_zone": "material",
        "naming": {
            "directory_key": key,
            "subject": "验收模板",
            "subject_is_manual": True,
            "formed_on": "2026-10-14",
            "version": "V1",
            "applicable_to": "测试专用",
        },
    }
    preview = await client.post(
        f"/api/v1/ingest/{task_id}/naming-preview", headers=headers(user), json=body
    )
    assert preview.status_code == 200, preview.text
    assert "验收操作模板" in preview.json()["canonical_name"]
    confirmed = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=headers(user),
        json={
            **body,
            "title": "验收模板",
            "summary": "虚构的验收摘要",
            "tags": ["验收"],
            "acknowledged_naming_warning_codes": [
                notice["code"] for notice in preview.json()["notices"]
            ],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "completed"
    new_id = confirmed.json()["result_asset_id"]
    detail = await client.get(f"/api/v1/knowledge/{new_id}", headers=headers(user))
    assert detail.status_code == 200, detail.text
    assert detail.json()["directory_key"] == key
    assert "验收操作模板" in detail.json()["directory_path"]

    asset_id = uuid.UUID(new_id)
    original = (await client.get(f"/api/v1/knowledge/{asset_id}", headers=headers(user))).json()
    asset = await db_session.get(KnowledgeAsset, asset_id)
    version = await db_session.get(KnowledgeAssetVersion, asset.current_version_id)
    file_query = select(
        KnowledgeAssetFileObject.id,
        KnowledgeAssetFileObject.storage_ref,
        KnowledgeAssetFileObject.file_hash,
    ).where(KnowledgeAssetFileObject.version_id == version.id)
    original_files = (await db_session.execute(file_query)).all()
    assert original_files
    original_bytes = [
        client._kap_storage.resolve_path(row.storage_ref).read_bytes() for row in original_files
    ]
    original_version_id, original_hash = version.id, version.file_hash
    edited = await client.patch(
        f"/api/v1/knowledge/{asset_id}/metadata",
        headers=headers(user),
        json={
            "expected_updated_at": original["updated_at"],
            "reason": "验收：修改目录",
            "directory_key": parent,
        },
    )
    assert edited.status_code == 200, edited.text
    await db_session.refresh(version)
    assert version.directory_key == parent
    current = (await client.get(f"/api/v1/knowledge/{asset_id}", headers=headers(user))).json()
    moved_back = await client.patch(
        f"/api/v1/knowledge/{asset_id}/metadata",
        headers=headers(user),
        json={
            "expected_updated_at": current["updated_at"],
            "reason": "验收：返回新目录",
            "directory_key": key,
        },
    )
    assert moved_back.status_code == 200, moved_back.text
    await db_session.refresh(version)
    assert version.directory_key == key
    assert version.id == original_version_id and version.file_hash == original_hash
    assert (await db_session.execute(file_query)).all() == original_files
    assert [
        client._kap_storage.resolve_path(row.storage_ref).read_bytes() for row in original_files
    ] == original_bytes


@pytest.mark.parametrize("count", [1, 25])
async def test_custom_directory_batch_uses_one_complete_snapshot(client, db_session, count):
    import uuid

    from sqlalchemy import event

    from app.models.identity import Project
    from app.models.ingest import IngestTask

    await client.get("/api/v1/admin/naming-rules", headers=headers(USER_BOSS))
    project = await db_session.get(Project, PROJECT_ALPHA)
    project.project_code, project.project_code_active = "ALPHA", True
    await db_session.commit()
    created = await client.post(
        "/api/v1/knowledge/directories",
        headers=headers(USER_PROJECT_MANAGER),
        json={
            "scope": "project",
            "project_id": str(PROJECT_ALPHA),
            "parent_key": "project.deliverables",
            "display_name": "批次验收",
        },
    )
    assert created.status_code == 201
    key = created.json()["directory_key"]
    tasks = [uuid.uuid4() for _ in range(count + 1)]
    for task_id in tasks:
        db_session.add(
            IngestTask(
                id=task_id,
                source="local_upload",
                source_file_ref="test/private",
                source_file_name="验收.txt",
                created_by=USER_PROJECT_MANAGER,
            )
        )
    await db_session.commit()
    statements = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        if "FROM knowledge_directories" in statement:
            statements.append(statement)

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = await client.post(
            "/api/v1/ingest/bulk-naming-preview",
            headers=headers(USER_PROJECT_MANAGER),
            json={
                "target_scope": "project",
                "target_project_id": str(PROJECT_ALPHA),
                "items": [
                    {
                        "task_id": str(task),
                        "confidentiality_level": "L2",
                        "naming": {
                            "directory_key": key if index < count else "project.custom_" + "a" * 32,
                            "subject": "验收",
                            "subject_is_manual": True,
                            "formed_on": "2026-10-14",
                            "version": "V1",
                        },
                    }
                    for index, task in enumerate(tasks)
                ],
            },
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert result.status_code == 200, result.text
    assert all(item["submittable"] for item in result.json()["items"][:count])
    assert not result.json()["items"][-1]["submittable"]
    assert len(statements) == 1

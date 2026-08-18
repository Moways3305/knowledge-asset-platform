"""Permission and no-leak contract tests for the first-party workbench API."""

from __future__ import annotations

import uuid

import pytest

from app.models.identity import ProjectMember, User, UserCompanyRole
from app.models.ingest import IngestTask
from app.models.review import ReviewTask
from app.seed.dev_seed import (
    KA_PROJECT_ALPHA_REVIEWABLE,
    KA_PROJECT_BETA_L3,
    PROJECT_ALPHA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
    USER_PROJECT_MANAGER,
)

OVERVIEW = "/api/v1/workbench/overview"
_LEAK_TOKENS = (
    "storage_ref",
    "source_file_ref",
    "weknora_kb_id",
    "weknora_doc_id",
    "model_id",
    "provider_id",
    "fetch_token",
    "download_url",
    "api_key",
    "secret",
)


def _headers(user_id: uuid.UUID) -> dict[str, str]:
    return {"X-Dev-User-Id": str(user_id)}


async def _create_business_user(
    db_session,
    *,
    company_role: str = "consultant",
    project_id: uuid.UUID | None = None,
    project_role: str = "consultant",
) -> uuid.UUID:
    user_id = uuid.uuid4()
    user = User(
        id=user_id,
        name="Workbench test user",
        email=f"workbench-{user_id}@test.local",
        status="active",
    )
    user.company_roles.append(UserCompanyRole(company_role=company_role, status="active"))
    if project_id is not None:
        user.project_members.append(
            ProjectMember(project_id=project_id, project_role=project_role, status="active")
        )
    db_session.add(user)
    await db_session.commit()
    return user_id


@pytest.mark.parametrize(
    ("user_id", "expected_status", "expected_projects"),
    [
        (USER_CONSULTANT, "available", {str(PROJECT_ALPHA)}),
        (USER_PROJECT_MANAGER, "available", {str(PROJECT_ALPHA)}),
        (USER_BOSS, "empty", set()),
        (USER_DIRECTOR, "empty", set()),
        (USER_ADMIN_ONLY, "forbidden", set()),
    ],
)
async def test_company_and_project_role_matrix(client, user_id, expected_status, expected_projects):
    response = await client.get(OVERVIEW, headers=_headers(user_id))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["projects"]["status"] == expected_status
    assert {item["project_id"] for item in body["projects"]["items"]} == expected_projects
    if user_id == USER_ADMIN_ONLY:
        assert body["todos"]["status"] == "forbidden"
        assert body["recent_activity"]["status"] == "forbidden"
        assert body["operations"]["status"] == "available"
        assert body["operations"]["data"]["title_visible"] is False
    if user_id in {USER_CONSULTANT, USER_PROJECT_MANAGER}:
        assert not any(
            item["task_type"] == "index_failed" for item in body["task_center"]["attention_items"]
        )


@pytest.mark.parametrize("project_role", ["consultant", "project_manager", "coach"])
async def test_each_project_role_only_sees_its_active_membership(client, db_session, project_role):
    user_id = await _create_business_user(
        db_session, project_id=PROJECT_ALPHA, project_role=project_role
    )

    response = await client.get(OVERVIEW, headers=_headers(user_id))

    assert response.status_code == 200
    projects = response.json()["projects"]
    assert projects["status"] == "available"
    assert projects["total"] == 1
    assert projects["items"][0]["project_id"] == str(PROJECT_ALPHA)
    assert projects["items"][0]["project_role"] == project_role


async def test_company_governance_roles_do_not_enumerate_project_workspaces(client):
    for user_id in (USER_BOSS, USER_DIRECTOR):
        response = await client.get(OVERVIEW, headers=_headers(user_id))
        assert response.status_code == 200
        body = response.json()
        assert body["projects"] == {
            "status": "empty",
            "error_code": None,
            "items": [],
            "total": 0,
        }
        cross_project = [
            item for item in body["recent_activity"]["items"] if item["scope"] == "project"
        ]
        assert cross_project
        assert all(item["confidentiality_level"] != "L5" for item in cross_project)
        assert "maintainer" not in response.text


async def test_project_member_recent_activity_includes_other_project_safe_summary(client):
    response = await client.get(OVERVIEW, headers=_headers(USER_CONSULTANT))

    assert response.status_code == 200
    recent_items = response.json()["recent_activity"]["items"]
    beta = next(item for item in recent_items if item["asset_id"] == str(KA_PROJECT_BETA_L3))
    assert beta["scope"] == "project"
    assert beta["confidentiality_level"] == "L3"
    assert beta["summary"].startswith("（脱敏）")


async def test_user_without_actionable_work_gets_empty_todos(client, db_session):
    user_id = await _create_business_user(db_session)

    response = await client.get(OVERVIEW, headers=_headers(user_id))

    assert response.status_code == 200
    assert response.json()["todos"] == {
        "status": "empty",
        "error_code": None,
        "items": [],
        "total": 0,
    }


async def test_submitted_review_waiting_for_another_user_is_not_actionable(client, db_session):
    user_id = await _create_business_user(db_session)
    db_session.add(
        ReviewTask(
            review_type="material_to_asset",
            trigger_source="internal_sharing",
            target_asset_id=KA_PROJECT_ALPHA_REVIEWABLE,
            target_project_id=PROJECT_ALPHA,
            target_scope="project",
            status="pending_reviewer",
            reviewer_user_id=USER_PROJECT_MANAGER,
            submitted_by=user_id,
        )
    )
    await db_session.commit()

    response = await client.get(OVERVIEW, headers=_headers(user_id))

    assert response.status_code == 200
    todos = response.json()["todos"]
    assert todos["status"] == "empty"
    assert todos["total"] == 0


async def test_only_confirm_ready_ingest_is_an_actionable_todo(client, db_session):
    user_id = await _create_business_user(db_session)
    db_session.add_all(
        [
            IngestTask(
                source="path_b_upload",
                source_file_ref="server-only/ready.txt",
                source_file_name="ready.txt",
                status="pending_confirmation",
                created_by=user_id,
            ),
            IngestTask(
                source="path_b_upload",
                source_file_ref="server-only/processing.txt",
                source_file_name="processing.txt",
                status="processing",
                created_by=user_id,
            ),
        ]
    )
    await db_session.commit()

    response = await client.get(OVERVIEW, headers=_headers(user_id))

    assert response.status_code == 200
    todos = response.json()["todos"]
    assert todos["status"] == "available"
    assert todos["total"] == 1
    assert todos["items"] == [
        {
            "key": "ingest_pending",
            "count": 1,
            "severity": "warning",
            "route_key": "upload",
            "action_key": "confirm_ingest",
        }
    ]
    assert "server-only" not in response.text


async def test_failed_and_rejected_ingest_appear_as_separate_ingest_failed_todo(client, db_session):
    """收窄口径：failed / rejected 任务归入独立 ingest_failed 待办（error），不混入 ingest_pending。"""
    user_id = await _create_business_user(db_session)
    db_session.add_all(
        [
            IngestTask(
                source="path_b_upload",
                source_file_ref="server-only/pending.txt",
                source_file_name="pending.txt",
                status="pending_confirmation",
                created_by=user_id,
            ),
            IngestTask(
                source="path_b_upload",
                source_file_ref="server-only/failed.txt",
                source_file_name="failed.txt",
                status="failed",
                created_by=user_id,
            ),
            IngestTask(
                source="path_b_upload",
                source_file_ref="server-only/rejected.txt",
                source_file_name="rejected.txt",
                status="rejected",
                created_by=user_id,
            ),
        ]
    )
    await db_session.commit()

    response = await client.get(OVERVIEW, headers=_headers(user_id))

    assert response.status_code == 200
    todos = response.json()["todos"]
    keys = {item["key"]: item for item in todos["items"]}
    # pending_confirmation → ingest_pending（1）
    assert keys["ingest_pending"]["count"] == 1
    assert keys["ingest_pending"]["severity"] == "warning"
    assert keys["ingest_pending"]["action_key"] == "confirm_ingest"
    # failed + rejected → ingest_failed（2，error）
    assert keys["ingest_failed"]["count"] == 2
    assert keys["ingest_failed"]["severity"] == "error"
    assert keys["ingest_failed"]["route_key"] == "upload"
    assert keys["ingest_failed"]["action_key"] == "retry_ingest"
    # ingest_failed 排在 ingest_pending 之前（error < warning）。
    assert todos["items"][0]["key"] == "ingest_failed"
    assert "server-only" not in response.text


async def test_one_section_failure_is_explicit_and_does_not_zero_other_sections(
    client, monkeypatch
):
    async def _fail_projects(*_args, **_kwargs):
        raise RuntimeError("SECRET-LIKE upstream detail")

    monkeypatch.setattr("app.services.workbench.build_projects", _fail_projects)

    response = await client.get(OVERVIEW, headers=_headers(USER_CONSULTANT))

    assert response.status_code == 200
    body = response.json()
    assert body["projects"] == {
        "status": "error",
        "error_code": "projects_unavailable",
        "items": [],
        "total": 0,
    }
    assert body["todos"]["status"] in {"available", "empty"}
    assert body["operations"]["status"] == "available"
    assert body["recent_activity"]["status"] in {"available", "empty"}
    assert "SECRET-LIKE" not in response.text


async def test_response_is_a_strict_safe_projection(client):
    response = await client.get(OVERVIEW, headers=_headers(USER_CONSULTANT))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"task_center", "todos", "operations", "projects", "recent_activity"}
    assert set(body["task_center"]) == {
        "status",
        "error_code",
        "summary",
        "priority_items",
        "my_tasks",
        "running_jobs",
        "attention_items",
        "recent_completed",
    }
    assert set(body["todos"]) == {"status", "error_code", "items", "total"}
    assert set(body["projects"]) == {"status", "error_code", "items", "total"}
    assert set(body["recent_activity"]) == {"status", "error_code", "items", "total"}
    assert set(body["operations"]) == {"status", "error_code", "data"}
    assert set(body["operations"]["data"]) == {
        "title_visible",
        "scope",
        "window_days",
        "cards",
        "indexing",
        "access",
        "lifecycle",
    }
    for item in body["todos"]["items"]:
        assert set(item) == {"key", "count", "severity", "route_key", "action_key"}
    for group in (
        "priority_items",
        "my_tasks",
        "running_jobs",
        "attention_items",
        "recent_completed",
    ):
        for item in body["task_center"][group]:
            assert set(item) == {
                "task_ref",
                "task_type",
                "object_name",
                "project_name",
                "status",
                "priority",
                "assignee",
                "responsibility",
                "created_at",
                "updated_at",
                "waiting_minutes",
                "next_action_key",
                "next_action_label",
                "route_key",
                "result_summary",
                "progress_total",
                "progress_success",
                "progress_failed",
            }
    for item in body["projects"]["items"]:
        assert set(item) == {
            "project_id",
            "name",
            "status",
            "project_role",
            "lifecycle_route_key",
            "lifecycle_phase_key",
        }
    for item in body["recent_activity"]["items"]:
        assert set(item) == {
            "asset_id",
            "title",
            "scope",
            "zone",
            "asset_type",
            "confidentiality_level",
            "summary",
            "project_name",
            "updated_at",
        }
    lowered = response.text.lower()
    for token in _LEAK_TOKENS:
        assert token not in lowered


async def test_task_center_maps_real_ingest_states_without_exposing_ids(client, db_session):
    user_id = await _create_business_user(db_session)
    task_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    db_session.add_all(
        [
            IngestTask(
                id=task_ids[0],
                source="path_b_upload",
                source_file_ref="server-only/confirm.docx",
                source_file_name="待确认方案.docx",
                status="pending_confirmation",
                created_by=user_id,
            ),
            IngestTask(
                id=task_ids[1],
                source="path_b_upload",
                source_file_ref="server-only/running.docx",
                source_file_name="处理中方案.docx",
                status="processing",
                created_by=user_id,
            ),
            IngestTask(
                id=task_ids[2],
                source="path_b_upload",
                source_file_ref="server-only/failed.docx",
                source_file_name="失败方案.docx",
                status="failed",
                created_by=user_id,
            ),
        ]
    )
    await db_session.commit()

    response = await client.get(OVERVIEW, headers=_headers(user_id))

    assert response.status_code == 200
    center = response.json()["task_center"]
    mine = {item["object_name"]: item for item in center["my_tasks"]}
    running = {item["object_name"]: item for item in center["running_jobs"]}
    assert mine["待确认方案.docx"]["status"] == "needs_action"
    assert mine["失败方案.docx"]["status"] == "failed"
    assert mine["失败方案.docx"]["priority"] == "urgent"
    assert running["处理中方案.docx"]["status"] == "processing"
    assert center["summary"]["needs_action"] == 2
    assert center["summary"]["running"] == 1
    assert all(str(task_id) not in response.text for task_id in task_ids)


async def test_task_center_does_not_include_review_waiting_for_another_user(client, db_session):
    user_id = await _create_business_user(db_session)
    db_session.add(
        ReviewTask(
            review_type="material_to_asset",
            trigger_source="internal_sharing",
            target_asset_id=KA_PROJECT_ALPHA_REVIEWABLE,
            target_project_id=PROJECT_ALPHA,
            target_scope="project",
            status="pending_reviewer",
            reviewer_user_id=USER_PROJECT_MANAGER,
            submitted_by=user_id,
        )
    )
    await db_session.commit()

    response = await client.get(OVERVIEW, headers=_headers(user_id))

    assert response.status_code == 200
    center = response.json()["task_center"]
    assert center["summary"]["needs_action"] == 0
    submitted = [item for item in center["my_tasks"] if item["task_type"] == "review"]
    assert len(submitted) == 1
    assert submitted[0]["status"] == "submitted"
    assert submitted[0]["responsibility"] == "由你提交"

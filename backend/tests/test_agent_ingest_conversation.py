"""Chat-only upload confirmation contracts and fail-closed boundaries."""

import json
import uuid

import pytest
from test_agent_operations import BASE, credential
from test_workbuddy_remote_mcp import _close_mcp, _mcp_session

from app.main import app, create_app
from app.models.identity import Project
from app.models.ingest import IngestTask
from app.seed.dev_seed import (
    PROJECT_ALPHA,
    PROJECT_BETA,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
    USER_PROJECT_MANAGER,
)


async def upload(client):
    response = await client.post(
        "/api/v1/ingest/upload",
        headers={"X-Dev-User-Id": str(USER_CONSULTANT)},
        files={"file": ("conversation.txt", "实施方法与项目复盘笔记".encode(), "text/plain")},
    )
    assert response.status_code == 200, response.text
    return response.json()["ingest_task_id"]


def confirmation(**changes):
    return dict(
        title="实施复盘",
        summary="实施方法与复盘",
        target_scope="personal",
        confidentiality_level="L2",
        directory_key="personal.learning_notes",
        **changes,
    )


@pytest.mark.parametrize(
    "user,company",
    [
        (USER_CONSULTANT, False),
        (USER_PROJECT_MANAGER, False),
        (USER_BOSS, True),
        (USER_DIRECTOR, True),
    ],
)
async def test_destinations_are_write_permissions_not_discovery(client, user, company):
    headers = await credential(client, user)
    result = await client.get(BASE + "/upload-destinations", headers=headers)
    assert result.status_code == 200, result.text
    destinations = result.json()["destinations"]
    assert any(row["scope"] == "company" for row in destinations) == company
    assert any(row["scope"] == "personal" and row["available"] for row in destinations)
    project_ids = {row["project_id"] for row in destinations if row["scope"] == "project"}
    assert str(PROJECT_BETA) not in project_ids
    if user in (USER_CONSULTANT, USER_PROJECT_MANAGER):
        assert str(PROJECT_ALPHA) in project_ids
    for row in destinations:
        if row["available"]:
            assert row["options"]["directories"]


async def test_prepare_then_confirm_without_visiting_kap(client, db_session):
    headers = await credential(client)
    task_id = await upload(client)
    path = BASE + "/ingest/" + task_id
    before = (await client.get(path, headers=headers)).json()
    result = await client.post(
        path + "/prepare-confirmation",
        headers=headers,
        json=confirmation(acknowledged_naming_warning_codes=["ai_suggestion_uncertain"]),
    )
    assert result.status_code == 200, result.text
    prepared = result.json()
    assert prepared["requires_user_confirmation"] is True
    assert prepared["summary"]["directory"]
    assert prepared["summary"]["target_scope"] == "personal"
    assert "confirmed" not in prepared["command"]
    assert prepared["command"]["expected_updated_at"] == before["expected_updated_at"]
    assert prepared["command"]["confirmation"]["acknowledged_naming_warning_codes"] == []
    after = (await client.get(path, headers=headers)).json()
    assert after["expected_updated_at"] == before["expected_updated_at"]
    assert after["progress"]["result_asset_id"] is None
    for forbidden in ("source_file_ref", "extracted_text_preview", "token_hash"):
        assert forbidden not in result.text
    body = {**prepared["command"], "confirmed": True}
    committed = await client.post(path + "/confirm", headers=headers, json=body)
    assert committed.status_code == 200, committed.text
    assert committed.json()["result_asset_id"]
    assert committed.json()["next_tool"] == "kap_get_ingest_details"
    assert (await client.post(path + "/confirm", headers=headers, json=body)).status_code == 409
    final = (await client.get(path, headers=headers)).json()
    assert final["progress"]["result_asset_id"] == committed.json()["result_asset_id"]


async def test_prepare_rejects_wrong_owner_directory_scope_and_locked_target(client, db_session):
    headers = await credential(client)
    task_id = await upload(client)
    path = BASE + "/ingest/" + task_id
    other = await credential(client, USER_PROJECT_MANAGER)
    assert (
        await client.post(path + "/prepare-confirmation", headers=other, json=confirmation())
    ).status_code == 404
    for changes in [
        {"directory_key": "company.introduction"},
        {"directory_key": "missing"},
        {"target_project_id": str(PROJECT_ALPHA)},
        {"summary": "", "one_liner": None},
    ]:
        body = {**confirmation(), **changes}
        assert (
            await client.post(path + "/prepare-confirmation", headers=headers, json=body)
        ).status_code == 422
    task = await db_session.get(IngestTask, uuid.UUID(task_id))
    task.target_scope = "project"
    task.target_project_id = PROJECT_ALPHA
    await db_session.commit()
    detail = (await client.get(path, headers=headers)).json()
    assert detail["destination"] == {
        "target_scope": "project",
        "target_project_id": str(PROJECT_ALPHA),
        "locked": True,
    }
    assert (
        await client.post(path + "/prepare-confirmation", headers=headers, json=confirmation())
    ).status_code == 409


async def test_new_tools_work_over_real_mcp_and_readonly_is_denied(client):
    headers = await credential(client)
    task_id = await upload(client)
    isolated = create_app()
    isolated.dependency_overrides.update(app.dependency_overrides)
    async with isolated.router.lifespan_context(isolated):
        resources = await _mcp_session(headers["Authorization"].split(" ")[1], isolated)
        try:
            session = resources[-1]
            await session.initialize()
            tools = {tool.name: tool for tool in (await session.list_tools()).tools}
            assert tools["kap_prepare_ingest_confirmation"].annotations.readOnlyHint
            targets = await session.call_tool("kap_list_upload_destinations", {})
            assert not targets.isError, targets
            prepared = await session.call_tool(
                "kap_prepare_ingest_confirmation",
                {
                    "task_id": task_id,
                    "confirmation": confirmation(),
                },
            )
            assert not prepared.isError, prepared
            data = json.loads(prepared.content[0].text)
            result = await session.call_tool(
                "kap_confirm_ingest",
                {
                    "task_id": task_id,
                    "command": {**data["command"], "confirmed": True},
                },
            )
            assert not result.isError, result
            assert json.loads(result.content[0].text)["result_asset_id"]
        finally:
            await _close_mcp(resources)
        readonly = await credential(client, enabled=False)
        resources = await _mcp_session(readonly["Authorization"].split(" ")[1], isolated)
        try:
            session = resources[-1]
            await session.initialize()
            for tool, args in [
                ("kap_list_upload_destinations", {}),
                (
                    "kap_prepare_ingest_confirmation",
                    {"task_id": task_id, "confirmation": confirmation()},
                ),
            ]:
                assert (await session.call_tool(tool, args)).isError
        finally:
            await _close_mcp(resources)


async def test_project_confirmation_returns_review_in_chat(client, db_session):
    # Publish the default directory policy and enable naming on the active project.
    center = await client.get(
        "/api/v1/admin/naming-rules", headers={"X-Dev-User-Id": str(USER_BOSS)}
    )
    assert center.status_code == 200, center.text
    project = await db_session.get(Project, PROJECT_ALPHA)
    project.project_code = "ALPHA"
    project.project_code_active = True
    project.force_review_on_ingest = True
    await db_session.commit()
    headers = await credential(client)
    task_id = await upload(client)
    path = BASE + "/ingest/" + task_id
    body = {
        **confirmation(),
        "target_scope": "project",
        "target_project_id": str(PROJECT_ALPHA),
        "directory_key": "project.retrospective",
        "naming": {
            "subject": "实施复盘",
            "formed_on": "2026-10-10",
            "version": "V1",
            "directory_key": "project.retrospective",
        },
    }
    prepared = await client.post(path + "/prepare-confirmation", headers=headers, json=body)
    assert prepared.status_code == 200, prepared.text
    data = prepared.json()
    assert data["summary"]["project_name"] == project.name
    assert data["preview"]["canonical_name"]
    command = {**data["command"], "confirmed": True}
    command["confirmation"]["acknowledged_naming_warning_codes"] = [
        notice["code"] for notice in data["preview"]["notices"]
    ]
    result = await client.post(path + "/confirm", headers=headers, json=command)
    assert result.status_code == 200, result.text
    assert result.json()["review_id"]
    assert result.json()["next_tool"] == "kap_get_review_details"
    assert result.json()["result_asset_id"] is None
    assert result.json()["index_status"] != "indexed"
    manager = await credential(client, USER_PROJECT_MANAGER)
    review = await client.get(BASE + "/reviews/" + result.json()["review_id"], headers=manager)
    assert review.status_code == 200, review.text


@pytest.mark.parametrize(
    "status,cancelled", [("processing", False), ("failed", False), ("pending_confirmation", True)]
)
async def test_prepare_rejects_unready_or_cancelled(client, db_session, status, cancelled):
    headers = await credential(client)
    task_id = await upload(client)
    task = await db_session.get(IngestTask, uuid.UUID(task_id))
    task.status = status
    task.cancel_requested = cancelled
    await db_session.commit()
    response = await client.post(
        BASE + "/ingest/" + task_id + "/prepare-confirmation",
        headers=headers,
        json=confirmation(),
    )
    assert response.status_code == 409, response.text

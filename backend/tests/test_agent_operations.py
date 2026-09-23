"""Operation opt-in, real transport, workflow authorization and stale command regressions."""

import json
import uuid

import pytest
from sqlalchemy import select
from test_workbuddy_remote_mcp import _close_mcp, _mcp_session

from app.main import app, create_app
from app.models.agent_registry import AgentWhitelistRule
from app.models.ingest import IngestTask
from app.seed.dev_seed import REVIEW_SEED, USER_CONSULTANT, USER_PROJECT_MANAGER
from app.services.storage import MAX_UPLOAD_BYTES
from app.services.upload_session_types import (
    SINGLE_FILE_MAX_BYTES,
    TRANSPORT_BATCH_MAX_BYTES,
    TRANSPORT_BATCH_MAX_FILES,
)

BASE = "/api/v1/agent-gateway/operations"


async def credential(client, user=USER_CONSULTANT, enabled=True):
    response = await client.post(
        "/api/v1/auth/workbuddy-token/regenerate",
        headers={"X-Dev-User-Id": str(user)},
        json={"operations_enabled": enabled},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["token"]}


def manifest():
    return {
        "session_id": str(uuid.uuid4()),
        "target_scope": "personal",
        "manifest": [
            {
                "client_file_key": "one",
                "file_name": "test.txt",
                "file_size": 12,
                "file_type": "text/plain",
                "transport_batch_index": 0,
            }
        ],
        "total_transport_batches": 1,
    }


async def test_legacy_read_only_and_revoked_credentials(client):
    headers = await credential(client, enabled=False)
    response = await client.post(BASE + "/uploads/init", headers=headers, json=manifest())
    assert response.status_code == 403
    assert (await client.get("/api/v1/agent-gateway/projects", headers=headers)).status_code == 200
    old = await credential(client)
    await credential(client, enabled=False)
    assert (
        await client.post(BASE + "/uploads/init", headers=old, json=manifest())
    ).status_code == 403


async def test_confirm_ingest_and_safe_retry(client):
    headers = await credential(client)
    uploaded = await client.post(
        "/api/v1/ingest/upload",
        headers={"X-Dev-User-Id": str(USER_CONSULTANT)},
        files={
            "file": (
                "notes.txt",
                "这是我的项目学习笔记，包含实施方法与复盘。".encode(),
                "text/plain",
            )
        },
    )
    assert uploaded.status_code == 200, uploaded.text
    task_id = uploaded.json()["ingest_task_id"]
    path = BASE + "/ingest/" + task_id
    detail = await client.get(path, headers=headers)
    assert detail.status_code == 200, detail.text
    body = {
        "expected_updated_at": detail.json()["expected_updated_at"],
        "confirmed": True,
        "confirmation": {
            "title": "学习笔记",
            "summary": "实施方法与复盘",
            "target_scope": "personal",
            "confidentiality_level": "L2",
            "directory_key": "personal.learning_notes",
        },
    }
    denied = await client.post(path + "/confirm", headers=headers, json=dict(body, confirmed=False))
    assert denied.status_code == 422
    result = await client.post(path + "/confirm", headers=headers, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["result_asset_id"]
    assert (await client.post(path + "/confirm", headers=headers, json=body)).status_code == 409
    state = await client.get(path, headers=headers)
    assert state.status_code == 200, state.text
    assert state.json()["progress"]["result_asset_id"] == result.json()["result_asset_id"]


async def test_multipart_upload_is_owned_and_replay_does_not_duplicate(client, db_session):
    headers = await credential(client)
    body = manifest()
    response = await client.post(BASE + "/uploads/init", headers=headers, json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["transport"]["max_file_bytes"] == MAX_UPLOAD_BYTES == SINGLE_FILE_MAX_BYTES
    assert data["transport"]["max_batch_bytes"] == TRANSPORT_BATCH_MAX_BYTES
    assert data["transport"]["max_files_per_batch"] == TRANSPORT_BATCH_MAX_FILES
    assert data["transport"]["single_file_batch_exception"] == {
        "file_count": 1,
        "max_batch_bytes": SINGLE_FILE_MAX_BYTES,
    }
    repeated = await client.post(BASE + "/uploads/init", headers=headers, json=body)
    assert repeated.json()["session"]["id"] == data["session"]["id"]
    item_id = data["session"]["items"][0]["id"]
    other = await credential(client, USER_PROJECT_MANAGER)
    assert (
        await client.get(BASE + "/uploads/" + body["session_id"], headers=other)
    ).status_code in (403, 404)
    form = {"batch_id": "fixed-batch", "batch_index": "0", "item_ids": json.dumps([item_id])}
    for _ in range(2):
        uploaded = await client.post(
            data["transport"]["path"],
            headers=headers,
            data=form,
            files={"files": ("test.txt", b"hello world!", "text/plain")},
        )
        assert uploaded.status_code == 200, uploaded.text
    assert (
        len(
            list(
                (
                    await db_session.scalars(
                        select(IngestTask).where(IngestTask.source_file_name == "test.txt")
                    )
                ).all()
            )
        )
        == 1
    )
    completed = await client.post(
        BASE + "/uploads/" + body["session_id"] + "/complete", headers=headers
    )
    assert completed.status_code == 200, completed.text
    task_id = uploaded.json()["items"][0]["ingest_task_id"]
    details = await client.get(BASE + "/ingest/" + task_id, headers=headers)
    assert details.status_code == 200, details.text
    assert "expected_updated_at" in details.json()
    assert "source_file_ref" not in details.text
    assert (await client.get(BASE + "/ingest/" + task_id, headers=other)).status_code == 404


@pytest.mark.parametrize("action", ["approve", "reject"])
async def test_review_decision_reuses_permissions_and_rejects_stale_retry(client, action):
    pm = await credential(client, USER_PROJECT_MANAGER)
    path = BASE + "/reviews/" + str(REVIEW_SEED)
    read = await client.get(path, headers=pm)
    assert read.status_code == 200, read.text
    body = {
        "expected_updated_at": read.json()["expected_updated_at"],
        "confirmed": True,
        "action": action,
        "comment": "已核验材料",
    }
    consultant = await credential(client)
    assert (await client.post(path + "/decision", headers=consultant, json=body)).status_code == 403
    invalid = dict(body, confirmed=False)
    assert (await client.post(path + "/decision", headers=pm, json=invalid)).status_code == 422
    stale = dict(body, expected_updated_at="2000-01-01T00:00:00Z")
    assert (await client.post(path + "/decision", headers=pm, json=stale)).status_code == 409
    decided = await client.post(path + "/decision", headers=pm, json=body)
    assert decided.status_code == 200, decided.text
    assert (await client.post(path + "/decision", headers=pm, json=body)).status_code == 409


async def test_restricted_or_managed_operations_rule_fails_closed(client, db_session):
    headers = await credential(client)
    rule = await db_session.scalar(
        select(AgentWhitelistRule).where(AgentWhitelistRule.bound_user_id == USER_CONSULTANT)
    )
    rule.allowed_scope = "company"
    await db_session.commit()
    assert (
        await client.post(BASE + "/uploads/init", headers=headers, json=manifest())
    ).status_code == 403
    rule.allowed_scope = None
    rule.is_self_service = False
    await db_session.commit()
    assert (
        await client.post(BASE + "/uploads/init", headers=headers, json=manifest())
    ).status_code == 403


async def test_real_mcp_operation_contract_and_read_only_denial(client):
    headers = await credential(client)
    isolated = create_app()
    isolated.dependency_overrides.update(app.dependency_overrides)
    async with isolated.router.lifespan_context(isolated):
        resources = await _mcp_session(headers["Authorization"].split(" ")[1], isolated)
        try:
            session = resources[-1]
            await session.initialize()
            result = await session.call_tool("kap_initialize_upload", {"upload": manifest()})
            assert not result.isError, result
            data = json.loads(result.content[0].text)
            assert data["transport"]["authentication"] == "same_bearer"
            assert "Bearer" not in str(data)
        finally:
            await _close_mcp(resources)
        readonly = await credential(client, enabled=False)
        resources = await _mcp_session(readonly["Authorization"].split(" ")[1], isolated)
        try:
            await resources[-1].initialize()
            result = await resources[-1].call_tool("kap_initialize_upload", {"upload": manifest()})
            assert result.isError
        finally:
            await _close_mcp(resources)

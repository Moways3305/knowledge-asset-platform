"""Real persistence/API lifecycle with synthetic model responses and private data."""

import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from test_maintenance_agent import headers

from app.db.utils import utc_now
from app.models.ai_workspace import (
    WorkspaceArtifact,
    WorkspaceEvent,
    WorkspaceMessage,
    WorkspaceRun,
    WorkspaceSession,
)
from app.models.identity import User
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetSummary
from app.schemas.ai_workspace import MessageCreate
from app.seed.dev_seed import KA_COMPANY_L2, USER_ADMIN_ONLY, USER_BOSS, USER_CONSULTANT
from app.services import ai_workspace as service
from app.services.llm_client import NullLLMClient
from app.services.maintenance_access import actor_context

URL = "/api/v1/ai-workspace"
CONSULTANT = headers(USER_CONSULTANT)
PHONE = "13800138000"


class Model:
    def __init__(self, *steps):
        self.steps = list(steps)
        self.prompts = []

    async def chat_completion(self, messages, **kwargs):
        self.prompts.append(messages)
        step = self.steps.pop(0) if self.steps else {"action": "answer", "content": "已完成"}
        if isinstance(step, Exception):
            raise step
        return json.dumps(step, ensure_ascii=False)


@pytest.fixture
def model(monkeypatch):
    instance = Model()

    async def resolve(*args, **kwargs):
        return instance

    monkeypatch.setattr(service, "resolve_generation_llm_client", resolve)
    return instance


async def create(client):
    response = await client.post(
        URL + "/sessions", headers=CONSULTANT, json={"request_id": str(uuid.uuid4())}
    )
    assert response.status_code == 201, response.text
    return URL + "/sessions/" + response.json()["id"]


async def send(client, path, *, content="请帮我整理访谈计划", request_id=None, context_key=None):
    response = await client.post(
        path + "/messages",
        headers=CONSULTANT,
        json={
            "request_id": str(request_id or uuid.uuid4()),
            "content": content,
            "model_ref": "system_default",
            "context_key": context_key,
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


async def test_private_multiturn_artifact_and_idempotence(client, model):
    model.steps = [
        {"action": "write_document", "title": "访谈计划", "content": "电话：" + PHONE},
        {"action": "answer", "content": "已整理。电话：" + PHONE},
    ]
    path = await create(client)
    request_id = uuid.uuid4()
    run = await send(client, path, content="整理资料，联系电话：" + PHONE, request_id=request_id)
    first = (await client.get(path, headers=CONSULTANT)).json()
    assert first["runs"][0]["status"] == "completed", first
    assert PHONE not in json.dumps(first, ensure_ascii=False)
    assert len(first["messages"]) == 2 and len(first["artifacts"]) == 1
    duplicate = await send(
        client, path, content="整理资料，联系电话：" + PHONE, request_id=request_id
    )
    assert duplicate["id"] == run["id"] and len(model.prompts) == 2
    await send(client, path, content="继续完善第二部分")
    assert any(m["content"].startswith("已整理") for m in model.prompts[-1])
    assert PHONE not in json.dumps(model.prompts, ensure_ascii=False)
    assert (await client.get(path, headers=headers(USER_BOSS))).status_code == 404
    assert (
        await client.get(URL + "/sessions", headers=headers(USER_ADMIN_ONLY))
    ).status_code == 403
    artifact = first["artifacts"][0]
    edit = {
        "title": "访谈计划更新",
        "content": "已手工编辑，电话：" + PHONE,
        "expected_revision": artifact["revision"],
    }
    changed = await client.patch(
        path + "/artifacts/" + artifact["id"], headers=CONSULTANT, json=edit
    )
    assert changed.status_code == 200 and changed.json()["revision"] == 2, changed.text
    assert PHONE not in changed.text
    assert (
        await client.patch(path + "/artifacts/" + artifact["id"], headers=CONSULTANT, json=edit)
    ).status_code == 409
    events = (await client.get(path + "/events?after=0", headers=CONSULTANT)).json()
    assert [e["id"] for e in events["events"]] == list(range(1, events["cursor"] + 1))
    assert PHONE not in json.dumps(events)
    assert (
        await client.get(path + f"/events?after={events['cursor']}", headers=CONSULTANT)
    ).json()["events"] == []
    assert (await client.delete(path, headers=CONSULTANT)).status_code == 204
    assert (await client.get(path, headers=CONSULTANT)).status_code == 404


async def test_run_failure_resume_and_private_errors(client, model, monkeypatch):
    model.steps = [ValueError("upstream credential " + PHONE)]
    path = await create(client)
    run = await send(client, path)
    snapshot = (await client.get(path, headers=CONSULTANT)).json()
    assert snapshot["runs"][0]["status"] == "failed"
    assert snapshot["runs"][0]["error_code"] == "response_error"
    assert PHONE not in json.dumps(snapshot)
    response = await client.post(
        path + f"/runs/{run['id']}/resume",
        headers=CONSULTANT,
        json={"request_id": str(uuid.uuid4())},
    )
    assert response.status_code == 202, response.text
    snapshot = (await client.get(path, headers=CONSULTANT)).json()
    assert [r["status"] for r in snapshot["runs"]] == ["completed"]
    assert [m["role"] for m in snapshot["messages"]] == ["user", "assistant"]
    # Invalid requests must not echo the original pasted text, including Pydantic's input field.
    invalid = await client.post(
        path + "/messages",
        headers=CONSULTANT,
        json={"request_id": "invalid", "content": PHONE, "model_ref": "system_default"},
    )
    assert invalid.status_code == 422 and PHONE not in invalid.text

    async def disabled(*args, **kwargs):
        return NullLLMClient()

    monkeypatch.setattr(service, "resolve_generation_llm_client", disabled)
    unavailable = await client.post(
        path + "/messages",
        headers=CONSULTANT,
        json={"request_id": str(uuid.uuid4()), "content": "再次尝试", "model_ref": "removed"},
    )
    assert unavailable.status_code == 409


async def test_stop_fences_late_model_result(client, model, sessionmaker_fixture):
    path = await create(client)
    session_id = uuid.UUID(path.rsplit("/", 1)[1])
    async with sessionmaker_fixture() as session:
        caller = await actor_context(session, USER_CONSULTANT, "consultant")
        run = await service.start(
            session,
            caller,
            session_id,
            MessageCreate(request_id=uuid.uuid4(), content="生成文档", model_ref="system_default"),
        )

    async def late_reply(messages, **kwargs):
        async with sessionmaker_fixture() as session:
            await service.stop(session, caller, session_id, run.id)
        return '{"action":"answer","content":"这个迟到的结果不应入库"}'

    model.chat_completion = late_reply
    await service.execute(sessionmaker_fixture, run.id)
    snapshot = (await client.get(path, headers=CONSULTANT)).json()
    assert snapshot["runs"][0]["status"] == "stopped"
    assert len(snapshot["messages"]) == 1 and snapshot["artifacts"] == []
    events = (await client.get(path + "/events", headers=CONSULTANT)).json()["events"]
    assert events[-1]["type"] == "stopped"


async def test_recovery_resumes_abandoned_run_and_drains_queue(client, model, sessionmaker_fixture):
    path = await create(client)
    session_id = uuid.UUID(path.rsplit("/", 1)[1])
    async with sessionmaker_fixture() as session:
        caller = await actor_context(session, USER_CONSULTANT, "consultant")
        run = await service.start(
            session,
            caller,
            session_id,
            MessageCreate(request_id=uuid.uuid4(), content="中断任务", model_ref="system_default"),
        )
        row = await session.get(WorkspaceRun, run.id)
        row.status, row.claim, row.lease_until = (
            "running",
            uuid.uuid4(),
            utc_now() - timedelta(minutes=5),
        )
        await session.commit()
    await service.recover(sessionmaker_fixture)
    snapshot = (await client.get(path, headers=CONSULTANT)).json()
    assert snapshot["runs"][0]["status"] == "completed"
    assert snapshot["runs"][0]["error_code"] is None
    async with sessionmaker_fixture() as session:
        await service.start(
            session,
            caller,
            session_id,
            MessageCreate(request_id=uuid.uuid4(), content="继续工作", model_ref="system_default"),
        )
    await service.recover(sessionmaker_fixture)
    assert (await client.get(path, headers=CONSULTANT)).json()["runs"][-1]["status"] == "completed"


async def test_event_cursor_does_not_skip_capped_page(client, model, db_session):
    path = await create(client)
    session_id, run_id = uuid.UUID(path.rsplit("/", 1)[1]), uuid.uuid4()
    for _index in range(105):
        await service.journal(db_session, session_id, run_id, "progress", "检查进度")
    await db_session.commit()
    page = (await client.get(path + "/events", headers=CONSULTANT)).json()
    assert len(page["events"]) == 100 and page["cursor"] == 100
    tail = (await client.get(path + "/events?after=100", headers=CONSULTANT)).json()
    assert [e["id"] for e in tail["events"]] == [101, 102, 103, 104, 105]


async def test_delete_removes_all_private_records(client, model, db_session):
    path = await create(client)
    await send(client, path)
    assert (await client.delete(path, headers=CONSULTANT)).status_code == 204
    for table in (
        WorkspaceArtifact,
        WorkspaceMessage,
        WorkspaceEvent,
        WorkspaceRun,
        WorkspaceSession,
    ):
        assert await db_session.scalar(select(table)) is None


async def test_knowledge_sources_follow_artifacts_and_later_turns(client, model, db_session):
    asset = await db_session.get(KnowledgeAsset, KA_COMPANY_L2)
    asset.title = "制造业访谈提纲"
    summary = await db_session.scalar(
        select(KnowledgeAssetSummary).where(
            KnowledgeAssetSummary.asset_id == asset.id,
            KnowledgeAssetSummary.version_id == asset.current_version_id,
            KnowledgeAssetSummary.summary_type == "detailed",
        )
    )
    summary.content = "工厂访谈样例，电话：" + PHONE
    await db_session.commit()
    model.steps = [
        {"action": "search_knowledge", "query": "制造业访谈提纲"},
        {
            "action": "write_document",
            "title": "工厂调研草稿",
            "content": "依据检索到的工厂访谈样例",
        },
        {"action": "answer", "content": "已生成工厂调研草稿"},
    ]
    path = await create(client)
    first_run = await send(client, path, context_key="company")
    snapshot = (await client.get(path, headers=CONSULTANT)).json()
    assert snapshot["runs"][0]["status"] == "completed", snapshot
    assert snapshot["artifacts"]
    refs = (await db_session.get(WorkspaceRun, uuid.UUID(first_run["id"]))).source_refs
    assert refs and "projection_digest" in refs[0] and "summary" not in refs[0]
    second_run = await send(client, path, content="继续解释这份草稿")
    second = await db_session.get(WorkspaceRun, uuid.UUID(second_run["id"]))
    assert second.source_refs == refs
    assert PHONE not in json.dumps(model.prompts, ensure_ascii=False)
    asset.confidentiality_level = "L5"
    await db_session.commit()
    hidden = (await client.get(path, headers=CONSULTANT)).json()
    assert hidden["artifacts"] == []
    assert all(
        "权限或版本已变化" in m["content"] for m in hidden["messages"] if m["role"] == "assistant"
    )
    await send(client, path, content="现在还能查看吗")
    latest_prompt = json.dumps(model.prompts[-1], ensure_ascii=False)
    assert "工厂调研草稿" not in latest_prompt and "工厂访谈样例" not in latest_prompt


async def test_live_identity_revocation_prevents_tool_read(
    client, model, sessionmaker_fixture, monkeypatch
):
    path = await create(client)
    reads = []

    async def revoked_response(messages, **kwargs):
        async with sessionmaker_fixture() as session:
            user = await session.get(User, USER_CONSULTANT)
            user.status = "inactive"
            await session.commit()
        return '{"action":"search_knowledge","query":"制造业"}'

    async def unexpected_search(*args, **kwargs):
        reads.append(True)
        return []

    model.chat_completion = revoked_response
    monkeypatch.setattr(service.workspace_tools, "search_context", unexpected_search)
    run = await send(client, path, context_key="company")
    assert reads == []
    async with sessionmaker_fixture() as session:
        row = await session.get(WorkspaceRun, uuid.UUID(run["id"]))
        assert row.status == "failed" and row.error_code == "access_changed"


async def test_heartbeat_fences_stale_recovery_and_busy_request(
    client, model, sessionmaker_fixture
):
    path = await create(client)
    session_id = uuid.UUID(path.rsplit("/", 1)[1])
    request = MessageCreate(request_id=uuid.uuid4(), content="慢任务", model_ref="system_default")
    async with sessionmaker_fixture() as session:
        caller = await actor_context(session, USER_CONSULTANT, "consultant")
        run = await service.start(session, caller, session_id, request)
        same = await service.start(session, caller, session_id, request)
        assert same.id == run.id
        claim = uuid.uuid4()
        row = await session.get(WorkspaceRun, run.id)
        row.status, row.claim, row.lease_until = "running", claim, utc_now() + timedelta(minutes=3)
        await session.commit()
    await service.recover(sessionmaker_fixture)
    busy = await client.post(
        path + "/messages",
        headers=CONSULTANT,
        json={
            "request_id": str(uuid.uuid4()),
            "content": "另一个任务",
            "model_ref": "system_default",
        },
    )
    assert busy.status_code == 409
    assert (await client.get(path, headers=CONSULTANT)).json()["runs"][0]["status"] == "running"


async def test_source_authorization_memo_is_per_request(client, db_session, monkeypatch):
    path = await create(client)
    session_id = uuid.UUID(path.rsplit("/", 1)[1])
    ref = {
        "asset_id": str(uuid.uuid4()),
        "version_id": str(uuid.uuid4()),
        "context_key": "company",
        "projection_digest": "test-digest",
    }
    for _ in range(50):
        run = WorkspaceRun(
            id=uuid.uuid4(),
            session_id=session_id,
            status="completed",
            instruction="继续整理",
            model_ref="system_default",
            context_key="company",
            source_refs=[ref, ref],
        )
        db_session.add(run)
        await db_session.flush()
        db_session.add(
            WorkspaceMessage(
                session_id=session_id, run_id=run.id, role="assistant", content="私有资料结果"
            )
        )
    await db_session.commit()
    calls, allowed = [], True

    async def validate(session, caller, refs):
        calls.extend(refs)
        return allowed

    monkeypatch.setattr(service.workspace_tools, "sources_available", validate)
    first = (await client.get(path, headers=CONSULTANT)).json()
    assert len(first["messages"]) == 50 and len(calls) == 1
    assert all(message["content"] == "私有资料结果" for message in first["messages"])
    allowed = False
    second = (await client.get(path, headers=CONSULTANT)).json()
    assert len(calls) == 2
    assert all("权限或版本已变化" in message["content"] for message in second["messages"])

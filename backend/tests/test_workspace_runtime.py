"""Durable tool intent, concrete approvals, waits and instruction steering."""

import json
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from test_ai_workspace import CONSULTANT, PHONE, URL, Model, send

from app.db.utils import utc_now
from app.models.ai_workspace import WorkspaceAction, WorkspaceArtifact, WorkspaceRun
from app.schemas.ai_workspace import MessageCreate, ResumeCommand
from app.seed.dev_seed import USER_CONSULTANT
from app.services import ai_workspace as service
from app.services import workspace_registry as registry
from app.services.maintenance_access import actor_context


@pytest.fixture
def model(monkeypatch):
    instance = Model()

    async def resolve(*args, **kwargs):
        return instance

    monkeypatch.setattr(service, "resolve_generation_llm_client", resolve)
    return instance


async def create_agent(client):
    response = await client.post(
        URL + "/sessions",
        headers=CONSULTANT,
        json={"request_id": str(uuid.uuid4()), "agent_key": "knowledge-maintenance"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["agent_key"] == "knowledge-maintenance"
    return URL + "/sessions/" + response.json()["id"]


@pytest.fixture
def business(monkeypatch):
    calls = []
    state = {"done": False, "fail": False}

    async def execute(session, caller, context_key, command, *, request_id, confirmed=False):
        calls.append((command, request_id, confirmed))
        action = command["action"]
        if action == "fake_write":
            if not confirmed:
                return {
                    "confirmation": {
                        "summary": "Confirm version v1",
                        "arguments": {"action": action, "id": "object-1", "version": "v1"},
                    }
                }
            if state["fail"]:
                raise ValueError("private detail " + PHONE)
            # Transactional durable side effect stands in for a domain outbox row.
            session.add(
                WorkspaceArtifact(
                    id=uuid.uuid5(request_id, "side-effect"),
                    session_id=state["session_id"],
                    run_id=state["run_id"],
                    title="Receipt",
                    content="done",
                )
            )
            return {"observation": {"receipt_summary": "Stored v1", "phone": PHONE}}
        if action in {"fake_wait", "fake_observe"}:
            if not state["done"]:
                return {
                    "observation": {"status": "working"},
                    "waiting": {
                        "action": "fake_observe",
                        "arguments": {"id": "job-1"},
                        "retry_after_seconds": 10,
                    },
                }
            return {"observation": {"receipt_summary": "Job checked complete"}}
        return {"observation": {"receipt_summary": "Inspected"}}

    async def sources(*args):
        return True

    def definitions():
        return [
            {
                "key": key,
                "label": key,
                "description": key,
                "input_schema": {},
                "mutating": key == "fake_write",
            }
            for key in ("fake_write", "fake_wait", "fake_observe", "fake_read")
        ]

    monkeypatch.setattr(
        registry,
        "maintenance_module",
        lambda: SimpleNamespace(
            execute=execute, definitions=definitions, sources_available=sources
        ),
    )
    return calls, state


async def test_concrete_approval_is_single_use_and_idempotent(
    client, model, business, sessionmaker_fixture
):
    calls, state = business
    path = await create_agent(client)
    state["session_id"] = uuid.UUID(path.rsplit("/", 1)[1])
    state["run_id"] = uuid.uuid4()
    model.steps = [
        {"action": "fake_write", "id": "object-1"},
        {"action": "answer", "content": "Task summary"},
    ]
    await send(client, path, request_id=state["run_id"], context_key="company")
    detail = (await client.get(path, headers=CONSULTANT)).json()
    pending = detail["runs"][0]["pending_action"]
    assert pending["arguments"]["version"] == "v1"
    assert detail["runs"][0]["status"] == "awaiting_confirmation"
    assert detail["artifacts"] == []
    assert calls[0][2] is False
    decision = {"request_id": str(uuid.uuid4()), "decision": "approve"}
    route = path + f"/runs/{state['run_id']}/actions/{pending['id']}"
    response = await client.post(route, headers=CONSULTANT, json=decision)
    assert response.status_code == 202, response.text
    assert (await client.post(route, headers=CONSULTANT, json=decision)).status_code == 202
    detail = (await client.get(path, headers=CONSULTANT)).json()
    assert detail["runs"][0]["status"] == "completed"
    assert len(detail["artifacts"]) == 1
    assert len(calls) == 2 and calls[0][1] == calls[1][1]
    assert calls[1][0] == pending["arguments"] and calls[1][2]
    assert PHONE not in json.dumps(detail) and PHONE not in json.dumps(model.prompts)
    assert "Stored v1" in detail["messages"][-1]["content"]


async def test_waiting_recovers_without_restarting_original_tool(
    client, model, business, sessionmaker_fixture
):
    calls, state = business
    path = await create_agent(client)
    model.steps = [{"action": "fake_wait"}, {"action": "answer", "content": "Done"}]
    sent = await send(client, path, context_key="company")
    detail = (await client.get(path, headers=CONSULTANT)).json()
    assert detail["runs"][0]["status"] == "waiting"
    assert detail["runs"][0]["waiting_reason"] == "external_task"
    assert len(model.prompts) == 1
    state["done"] = True
    async with sessionmaker_fixture() as session:
        run = await session.get(WorkspaceRun, uuid.UUID(sent["id"]))
        run.next_wake_at = utc_now() - timedelta(seconds=1)
        await session.commit()
    await service.recover(sessionmaker_fixture)
    detail = (await client.get(path, headers=CONSULTANT)).json()
    assert detail["runs"][0]["status"] == "completed"
    assert [call[0]["action"] for call in calls] == ["fake_wait", "fake_observe"]
    assert len(detail["actions"]) == 1 and detail["actions"][0]["status"] == "completed"


async def test_supplement_discards_inflight_decision_and_survives_restart(
    client, model, sessionmaker_fixture
):
    path = await create_agent(client)
    session_id = uuid.UUID(path.rsplit("/", 1)[1])
    async with sessionmaker_fixture() as session:
        caller = await actor_context(session, USER_CONSULTANT, "consultant")
        run = await service.start(
            session,
            caller,
            session_id,
            MessageCreate(
                request_id=uuid.uuid4(),
                content="Original goal",
                model_ref="system_default",
                context_key="company",
            ),
        )
    prompts = []

    async def reply(messages, **kwargs):
        prompts.append(messages)
        if len(prompts) == 1:
            async with sessionmaker_fixture() as session:
                await service.resume(
                    session,
                    caller,
                    session_id,
                    run.id,
                    ResumeCommand(
                        request_id=uuid.uuid4(), content="Only investigate, do not write"
                    ),
                )
            return '{"action":"write_document","title":"Stale decision","content":"Discard me"}'
        assert "Only investigate" in json.dumps(messages)
        return '{"action":"answer","content":"I will investigate first"}'

    model.chat_completion = reply
    await service.execute(sessionmaker_fixture, run.id)
    detail = (await client.get(path, headers=CONSULTANT)).json()
    assert len(detail["messages"]) == 3 and detail["artifacts"] == []
    assert detail["runs"][0]["status"] == "completed"
    assert "I will investigate first" in detail["messages"][-1]["content"]


async def test_planned_step_is_replayed_once_after_worker_loss(
    client, model, business, sessionmaker_fixture
):
    calls, _ = business
    path = await create_agent(client)
    session_id = uuid.UUID(path.rsplit("/", 1)[1])
    async with sessionmaker_fixture() as session:
        caller = await actor_context(session, USER_CONSULTANT, "consultant")
        out = await service.start(
            session,
            caller,
            session_id,
            MessageCreate(
                request_id=uuid.uuid4(),
                content="Inspect",
                model_ref="system_default",
                context_key="company",
            ),
        )
        run = await session.get(WorkspaceRun, out.id)
        action = WorkspaceAction(
            id=uuid.uuid4(),
            session_id=session_id,
            run_id=run.id,
            seq=1,
            tool="fake_read",
            label="Inspect",
            arguments={"action": "fake_read"},
        )
        session.add(action)
        run.status, run.claim, run.lease_until = (
            "running",
            uuid.uuid4(),
            utc_now() - timedelta(minutes=5),
        )
        run.step_count, run.runtime_state = (
            1,
            {
                "pending_action_id": str(action.id),
                "transcript": [{"role": "user", "content": "Inspect"}],
            },
        )
        await session.commit()
    await service.recover(sessionmaker_fixture)
    await service.recover(sessionmaker_fixture)
    assert len(calls) == 1
    detail = (await client.get(path, headers=CONSULTANT)).json()
    assert detail["runs"][0]["status"] == "completed"
    assert detail["actions"][0]["observation"]["receipt_summary"] == "Inspected"


async def test_stop_pending_approval_and_resume_does_not_grant_it(client, model, business):
    calls, _ = business
    path = await create_agent(client)
    model.steps = [{"action": "fake_write", "id": "object-1"}]
    run = await send(client, path, context_key="company")
    assert (
        await client.post(path + f"/runs/{run['id']}/stop", headers=CONSULTANT)
    ).status_code == 200
    continued = await client.post(
        path + f"/runs/{run['id']}/resume",
        headers=CONSULTANT,
        json={"request_id": str(uuid.uuid4())},
    )
    assert continued.status_code == 202, continued.text
    detail = (await client.get(path, headers=CONSULTANT)).json()
    assert detail["runs"][0]["status"] == "awaiting_confirmation" and len(calls) == 1
    pending = detail["runs"][0]["pending_action"]
    denied = await client.post(
        path + f"/runs/{run['id']}/actions/{pending['id']}",
        headers=CONSULTANT,
        json={"request_id": str(uuid.uuid4()), "decision": "reject"},
    )
    assert denied.status_code == 202 and len(calls) == 1
    assert (await client.get(path, headers=CONSULTANT)).json()["runs"][0]["status"] == "completed"


async def test_invalid_schema_arguments_never_persist_extra_personal_keys(client, model):
    path = await create_agent(client)
    model.steps = [
        {"action": "search_knowledge", "query": "test", PHONE: "private payload"},
        {"action": "answer", "content": "Please clarify the search"},
    ]
    await send(client, path, context_key="company")
    detail = (await client.get(path, headers=CONSULTANT)).json()
    assert detail["runs"][0]["status"] == "completed"
    assert detail["actions"][0]["observation"]["error"] == "invalid_tool_arguments"
    assert PHONE not in json.dumps(detail) and "private payload" not in json.dumps(model.prompts)


def test_schema_and_redaction_preserve_only_structural_uuid_fields():
    identifier = "11111111-2222-4333-8444-123456789012"
    data = registry.safe_data(
        {
            "issue_id": identifier,
            "expected_version_id": identifier,
            "issue_ids": [identifier],
            "context_key": "project:" + identifier,
            PHONE: PHONE,
        }
    )
    assert data["issue_id"] == identifier
    assert data["expected_version_id"] == identifier
    assert data["issue_ids"] == [identifier]
    assert data["context_key"] == "project:" + identifier
    assert PHONE not in json.dumps(data)
    registry.validate_input(
        {"id": identifier},
        {
            "type": "object",
            "properties": {"id": {"type": "string", "format": "uuid"}},
            "additionalProperties": False,
        },
    )
    with pytest.raises(ValueError):
        registry.validate_input(
            {"id": PHONE},
            {"type": "object", "properties": {"id": {"type": "string", "format": "uuid"}}},
        )


async def test_stale_confirmation_discards_revoked_transcript_before_model(
    client, model, business, sessionmaker_fixture, monkeypatch
):
    calls, _ = business
    path = await create_agent(client)
    model.steps = [
        {"action": "fake_write", "id": "object-1"},
        {"action": "answer", "content": "Need fresh evidence"},
    ]
    sent = await send(client, path, context_key="company")
    snapshot = (await client.get(path, headers=CONSULTANT)).json()
    pending = snapshot["runs"][0]["pending_action"]
    ref = {"kind": "maintenance", "source_type": "library", "context_key": "company"}
    async with sessionmaker_fixture() as session:
        run = await session.get(WorkspaceRun, uuid.UUID(sent["id"]))
        action = await session.get(WorkspaceAction, uuid.UUID(pending["id"]))
        run.source_refs, action.source_refs = [ref], [ref]
        run.runtime_state = {
            **run.runtime_state,
            "transcript": [
                {"role": "user", "content": "Original goal"},
                {"role": "user", "content": "Revoked confidential evidence"},
            ],
        }
        await session.commit()

    async def sources(session, caller, refs):
        return not refs

    monkeypatch.setattr(registry, "sources_available", sources)
    result = await client.post(
        path + f"/runs/{sent['id']}/actions/{pending['id']}",
        headers=CONSULTANT,
        json={"request_id": str(uuid.uuid4()), "decision": "approve"},
    )
    assert result.status_code == 202, result.text
    assert len(calls) == 1
    assert "Revoked confidential evidence" not in json.dumps(model.prompts[-1])
    snapshot = (await client.get(path, headers=CONSULTANT)).json()
    assert snapshot["runs"][0]["status"] == "completed"


async def test_reading_draft_from_stopped_run_propagates_its_source(client, model, db_session):
    from test_ai_workspace import create

    from app.models.knowledge import KnowledgeAsset
    from app.seed.dev_seed import KA_COMPANY_L2

    asset = await db_session.get(KnowledgeAsset, KA_COMPANY_L2)
    asset.title = "制造业访谈提纲"
    await db_session.commit()
    path = await create(client)
    model.steps = [
        {"action": "search_knowledge", "query": "制造业访谈提纲"},
        {"action": "write_document", "title": "Source draft", "content": "Private draft evidence"},
        {"action": "answer", "content": "Saved"},
    ]
    first = await send(client, path, context_key="company")
    detail = (await client.get(path, headers=CONSULTANT)).json()
    artifact = detail["artifacts"][0]
    original = await db_session.get(WorkspaceArtifact, uuid.UUID(artifact["id"]))
    assert original.source_refs
    run = await db_session.get(WorkspaceRun, uuid.UUID(first["id"]))
    run.status, run.source_refs = "stopped", []
    await db_session.commit()
    model.steps = [
        {"action": "read_document", "id": artifact["id"]},
        {
            "action": "write_document",
            "title": "Derived draft",
            "content": "Derived private evidence",
        },
        {"action": "answer", "content": "Saved derived"},
    ]
    second = await send(client, path, content="Continue using the draft")
    derived = await db_session.get(WorkspaceRun, uuid.UUID(second["id"]))
    assert derived.source_refs == original.source_refs
    asset.confidentiality_level = "L5"
    await db_session.commit()
    hidden = (await client.get(path, headers=CONSULTANT)).json()
    assert hidden["artifacts"] == []


def test_only_known_sha256_fields_preserve_numeric_digest_segments():
    value = "a" * 25 + PHONE + "b" * 28
    assert len(value) == 64
    safe = registry.safe_data(
        {
            "projection_digest": value,
            "recipients_signature": value,
            "content": value,
            "arbitrary_digest": value,
        }
    )
    assert safe["projection_digest"] == safe["recipients_signature"] == value
    assert PHONE not in safe["content"] and PHONE not in safe["arbitrary_digest"]
    assert PHONE not in registry.safe_data({"projection_digest": PHONE})["projection_digest"]


async def test_supplement_cancels_approved_but_unstarted_action(
    client, model, business, sessionmaker_fixture
):
    calls, _ = business
    path = await create_agent(client)
    sid = uuid.UUID(path.rsplit("/", 1)[1])
    async with sessionmaker_fixture() as session:
        caller = await actor_context(session, USER_CONSULTANT, "consultant")
        out = await service.start(
            session,
            caller,
            sid,
            MessageCreate(
                request_id=uuid.uuid4(),
                content="Original goal",
                model_ref="system_default",
                context_key="company",
            ),
        )
        run = await session.get(WorkspaceRun, out.id)
        action = WorkspaceAction(
            id=uuid.uuid4(),
            session_id=sid,
            run_id=run.id,
            seq=1,
            tool="fake_write",
            label="Write",
            status="approved",
            arguments={"action": "fake_write", "id": "object-1", "version": "v1"},
        )
        session.add(action)
        run.step_count = 1
        run.runtime_state = {
            "pending_action_id": str(action.id),
            "transcript": [{"role": "user", "content": "Original goal"}],
        }
        await session.commit()
        await service.resume(
            session,
            caller,
            sid,
            run.id,
            ResumeCommand(request_id=uuid.uuid4(), content="Only investigate, skip the write"),
        )
    await service.execute(sessionmaker_fixture, out.id)
    assert calls == []
    assert "Only investigate" in json.dumps(model.prompts[-1])
    detail = (await client.get(path, headers=CONSULTANT)).json()
    assert detail["actions"][0]["status"] == "rejected"
    assert detail["runs"][0]["status"] == "completed" and detail["artifacts"] == []


@pytest.mark.parametrize("change", ["permission", "version"])
@pytest.mark.parametrize("intent_status", ["planned", "approved"])
async def test_source_change_cancels_saved_intent_without_republishing_old_arguments(
    client, model, sessionmaker_fixture, monkeypatch, change, intent_status
):
    from test_ai_workspace import create

    from app.models.knowledge import KnowledgeAsset, KnowledgeAssetSummary, KnowledgeAssetVersion
    from app.seed.dev_seed import KA_COMPANY_L2

    marker = "Synthetic withdrawn confidential evidence"
    async with sessionmaker_fixture() as session:
        asset = await session.get(KnowledgeAsset, KA_COMPANY_L2)
        asset.title = "制造业访谈提纲"
        summary = await session.scalar(
            select(KnowledgeAssetSummary).where(
                KnowledgeAssetSummary.asset_id == asset.id,
                KnowledgeAssetSummary.version_id == asset.current_version_id,
                KnowledgeAssetSummary.summary_type == "detailed",
            )
        )
        summary.content = marker
        await session.commit()
    original_save = service.save_decision
    captured = []

    async def change_after_intent(maker, run_id, claim, result, input_version):
        finished = await original_save(maker, run_id, claim, result, input_version)
        if result.get("action") == "write_document":
            async with maker() as session:
                action = await session.scalar(
                    select(WorkspaceAction).where(
                        WorkspaceAction.run_id == run_id, WorkspaceAction.tool == "write_document"
                    )
                )
                assert action.source_refs, (
                    "The intent must freeze its input provenance before execution"
                )
                captured.append(action.id)
                action.status = intent_status
                asset = await session.get(KnowledgeAsset, KA_COMPANY_L2)
                if change == "permission":
                    asset.confidentiality_level = "L5"
                else:
                    old = await session.get(KnowledgeAssetVersion, asset.current_version_id)
                    old.version_status = "superseded"
                    await session.flush()
                    current = KnowledgeAssetVersion(
                        id=uuid.uuid4(),
                        asset_id=asset.id,
                        version_no="V2-regression",
                        version_status="active",
                        created_by=USER_CONSULTANT,
                        supersedes_version_id=old.id,
                    )
                    session.add(current)
                    await session.flush()
                    asset.current_version_id = current.id
                await session.commit()
        return finished

    monkeypatch.setattr(service, "save_decision", change_after_intent)
    path = await create(client)
    model.steps = [
        {"action": "search_knowledge", "query": "制造业访谈提纲"},
        {"action": "write_document", "title": "Outdated draft", "content": marker},
        {"action": "answer", "content": "Need to read current sources again"},
    ]
    await send(client, path, context_key="company")
    assert len(captured) == 1
    snapshot = (await client.get(path, headers=CONSULTANT)).json()
    assert snapshot["runs"][0]["status"] == "completed"
    assert snapshot["artifacts"] == []
    assert marker not in json.dumps(snapshot) and marker not in json.dumps(model.prompts[-1])
    async with sessionmaker_fixture() as session:
        action = await session.get(WorkspaceAction, captured[0])
        assert action.status == "rejected" and action.observation["error"] == "source_changed"
        run = await session.get(WorkspaceRun, action.run_id)
        assert "pending_action_id" not in run.runtime_state
        assert marker not in json.dumps(run.runtime_state)
        assert await session.scalar(select(WorkspaceArtifact)) is None

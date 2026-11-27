"""Real DB business tools: live authority, safe observations and recheck lifecycle."""

import json
import uuid
from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from test_ai_workspace import Model
from test_maintenance_agent import configure, content_asset, headers
from test_maintenance_batches import Segments, finish

from app.db.utils import utc_now
from app.models.ai_workspace import WorkspaceRun
from app.models.identity import User
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.maintenance_agent import (
    MaintenanceDigestIssue,
    MaintenanceIssue,
    MaintenancePolicy,
    MaintenanceRun,
    MaintenanceRunItem,
)
from app.seed.dev_seed import KA_COMPANY_L2, KA_PERSONAL, USER_BOSS, USER_CONSULTANT
from app.services import ai_workspace as runtime
from app.services import maintenance_access as access
from app.services import maintenance_workspace_tools as tools
from app.services.maintenance_replacement import continue_on_replacement

PHONE = "13800138000"
EMAIL = "sensitive-person@example.com"


async def actor(session, user=USER_BOSS):
    return await access.actor_context(session, user, "boss" if user == USER_BOSS else "consultant")


async def issue_fixture(session, policy_id, *, asset_id=KA_COMPANY_L2, rule="personal_information"):
    asset = await session.get(KnowledgeAsset, asset_id)
    row = MaintenanceIssue(
        policy_id=uuid.UUID(policy_id),
        asset_id=asset_id,
        version_id=asset.current_version_id,
        rule=rule,
        category="privacy" if rule == "personal_information" else "availability",
        fingerprint="fixture",
        suspected=True,
        evidence={
            "basis": "local_personal_information_check",
            "total": 2,
            "counts": {"phone": 1, "email": 1},
            "quote": f"联系人 王明 电话 {PHONE} 邮箱 {EMAIL}",
            "unknown_secret": EMAIL,
            "locations": [{"source": "body", "category": "phone", "start": 5, "end": 16}],
        },
    )
    session.add(row)
    await session.commit()
    return row.id


async def invoke(session, caller, action, *, confirmed=False, **kwargs):
    return await tools.execute(
        session,
        caller,
        "company",
        {"action": action, **kwargs},
        request_id=uuid.uuid4(),
        confirmed=confirmed,
    )


async def test_closed_registry_personal_scope_and_model_confirmation_do_not_grant_authority(
    client,
    sessionmaker_fixture,
):
    policy = await configure(client)
    async with sessionmaker_fixture() as session:
        caller = await actor(session)
        issue_id = await issue_fixture(session, policy["id"])
        proposed = await invoke(
            session,
            caller,
            "follow_maintenance_issue",
            issue_id=str(issue_id),
            **{"approved": True, "confirmed_by_model": True},
        )
        assert proposed["confirmation"]
        assert (await session.get(MaintenanceIssue, issue_id)).status == "open"
        with pytest.raises(HTTPException):
            await tools.execute(
                session,
                caller,
                "personal",
                {"action": "start_maintenance_scan"},
                request_id=uuid.uuid4(),
            )
        with pytest.raises(HTTPException):
            await invoke(session, caller, "resolve_maintenance_issue", issue_id=str(issue_id))
        definitions = {item["key"]: item for item in tools.definitions()}
        assert "issue_id" not in definitions["observe_maintenance_scan"]["input_schema"]["required"]


async def test_live_role_and_delegation_revocation_with_cached_caller(client, sessionmaker_fixture):
    policy = await configure(client)
    async with sessionmaker_fixture() as session:
        issue_id = await issue_fixture(session, policy["id"])
        asset = await session.get(KnowledgeAsset, KA_COMPANY_L2)
        asset.maintainer_user_id, asset.maintenance_delegated = USER_CONSULTANT, True
        await session.commit()
        caller = await actor(session, USER_CONSULTANT)
        result = await invoke(session, caller, "inspect_maintenance_issue", issue_id=str(issue_id))
        assert await tools.sources_available(session, caller, result["sources"])
        asset.maintenance_delegated = False
        await session.commit()
        assert not await tools.sources_available(session, caller, result["sources"])
        with pytest.raises(HTTPException) as denied:
            await invoke(session, caller, "inspect_maintenance_issue", issue_id=str(issue_id))
        assert denied.value.status_code == 404
        boss = await actor(session)
        user = await session.get(User, USER_BOSS)
        user.status = "inactive"
        await session.commit()
        with pytest.raises(HTTPException) as revoked:
            await invoke(session, boss, "maintenance_overview")
        assert revoked.value.status_code == 403


async def test_historical_raw_evidence_never_enters_observation_report_or_confirmation(
    client,
    sessionmaker_fixture,
):
    policy = await configure(client)
    async with sessionmaker_fixture() as session:
        issue_id = await issue_fixture(session, policy["id"])
        caller = await actor(session)
        outputs = [
            await invoke(session, caller, "inspect_maintenance_issue", issue_id=str(issue_id)),
            await invoke(session, caller, "prepare_maintenance_report", issue_ids=[str(issue_id)]),
            await invoke(session, caller, "notify_maintenance_issue", issue_id=str(issue_id)),
        ]
        wire = json.dumps(outputs, ensure_ascii=False)
        assert PHONE not in wire and EMAIL not in wire and "王明" not in wire
        assert "unknown_secret" not in wire and "quote" not in wire
        assert outputs[1]["observation"]["source_modified"] is False
        assert outputs[1]["observation"]["saved"] is False
        # A regular reader must not discover otherwise hidden maintenance facts.
        reader = await actor(session, USER_CONSULTANT)
        with pytest.raises(HTTPException):
            await invoke(session, reader, "inspect_maintenance_issue", issue_id=str(issue_id))


async def test_confirmed_follow_is_atomic_with_runtime_receipt_and_checks_revision(
    client,
    sessionmaker_fixture,
):
    policy = await configure(client)
    async with sessionmaker_fixture() as session:
        issue_id = await issue_fixture(session, policy["id"])
        caller = await actor(session)
        prepared = await invoke(session, caller, "follow_maintenance_issue", issue_id=str(issue_id))
        arguments = prepared["confirmation"]["arguments"]
        await tools.execute(
            session, caller, "company", arguments, request_id=uuid.uuid4(), confirmed=True
        )
        assert (await session.get(MaintenanceIssue, issue_id)).status == "in_progress"
        # The tool cannot commit behind the harness' claim fence.
        await session.rollback()
        assert (await session.get(MaintenanceIssue, issue_id)).status == "open"
        policy_row = await session.get(MaintenancePolicy, uuid.UUID(policy["id"]))
        policy_row.revision += 1
        await session.commit()
        with pytest.raises(HTTPException) as stale:
            await tools.execute(
                session, caller, "company", arguments, request_id=uuid.uuid4(), confirmed=True
            )
        assert stale.value.status_code == 409


async def test_scan_uses_real_queue_waits_and_excludes_personal_assets(
    client, sessionmaker_fixture
):
    await configure(client)
    async with sessionmaker_fixture() as session:
        caller = await actor(session)
        first = await invoke(session, caller, "start_maintenance_scan")
        second = await invoke(session, caller, "start_maintenance_scan")
        assert first["confirmation"] is None
        assert first["waiting"] and first["observation"]["finished"] is False
        assert first["observation"]["run_id"] == second["observation"]["run_id"]
        assert await session.scalar(select(func.count()).select_from(MaintenanceRun)) == 1
        assert not await session.scalar(
            select(MaintenanceRunItem.id).where(MaintenanceRunItem.asset_id == KA_PERSONAL)
        )
        observed = await invoke(
            session, caller, "observe_maintenance_scan", run_id=first["observation"]["run_id"]
        )
        assert observed["waiting"] and not observed["observation"]["coverage_complete"]
        assert await tools.sources_available(session, caller, observed["sources"])
        asset = await session.get(KnowledgeAsset, KA_COMPANY_L2)
        asset.scope = "personal"
        await session.flush()
        assert not await tools.sources_available(session, caller, observed["sources"])
        await session.rollback()
        assert await session.scalar(select(func.count()).select_from(MaintenanceRun)) == 0


async def test_reminders_merge_and_recheck_recipients_before_confirm(client, sessionmaker_fixture):
    policy = await configure(client)
    async with sessionmaker_fixture() as session:
        issue_id = await issue_fixture(session, policy["id"])
        caller = await actor(session)
        prepared = await invoke(session, caller, "notify_maintenance_issue", issue_id=str(issue_id))
        arguments = prepared["confirmation"]["arguments"]
        for _ in range(2):
            result = await tools.execute(
                session, caller, "company", arguments, request_id=uuid.uuid4(), confirmed=True
            )
            assert result["observation"]["notification_status"] == "merged_into_daily_digest"
        await session.commit()
        assert (
            await session.scalar(select(func.count()).select_from(MaintenanceDigestIssue))
            == result["observation"]["recipient_count"]
        )
        asset = await session.get(KnowledgeAsset, KA_COMPANY_L2)
        asset.maintainer_user_id, asset.maintenance_delegated = USER_CONSULTANT, True
        await session.commit()
        with pytest.raises(HTTPException) as changed:
            await tools.execute(
                session, caller, "company", arguments, request_id=uuid.uuid4(), confirmed=True
            )
        assert changed.value.status_code == 409


async def test_version_replacement_keeps_issue_then_real_recheck_closes_it(
    client,
    sessionmaker_fixture,
    tmp_path,
):
    maker = sessionmaker_fixture
    policy = await configure(client, content=True)
    old_id, storage = await content_asset(maker, tmp_path, body="电话 " + PHONE)
    new_id, _ = await content_asset(maker, tmp_path, body="经过修订的知识资料和实施方法。")
    async with maker() as session:
        issue_id = await issue_fixture(session, policy["id"], asset_id=old_id)
        caller = await actor(session)
        initial = await invoke(session, caller, "inspect_maintenance_issue", issue_id=str(issue_id))
        source, target = (
            await session.get(KnowledgeAsset, old_id),
            await session.get(KnowledgeAsset, new_id),
        )
        source.asset_status, source.replacement_asset_id = "archived", new_id
        target_version = await session.get(KnowledgeAssetVersion, target.current_version_id)
        target_version.weknora_parse_status = "processing"
        policy_row = await session.get(MaintenancePolicy, uuid.UUID(policy["id"]))
        await continue_on_replacement(session, policy_row, source, target)
        await session.commit()
        carried = await invoke(session, caller, "inspect_maintenance_issue", issue_id=str(issue_id))
        assert carried["observation"]["asset_id"] == str(new_id)
        assert carried["observation"]["requires_recheck"]
        assert not carried["observation"]["recheck_passed"]
        assert not await tools.sources_available(session, caller, initial["sources"])
    await finish(maker, Segments(), storage)
    async with maker() as session:
        caller = await actor(session)
        pending = await invoke(session, caller, "inspect_maintenance_issue", issue_id=str(issue_id))
        assert pending["observation"]["status"] == "open"
        target = await session.get(KnowledgeAsset, new_id)
        version = await session.get(KnowledgeAssetVersion, target.current_version_id)
        version.weknora_parse_status = "completed"
        await session.commit()
        proposal = await invoke(
            session, caller, "request_maintenance_recheck", issue_id=str(issue_id)
        )
        queued = await tools.execute(
            session,
            caller,
            "company",
            proposal["confirmation"]["arguments"],
            request_id=uuid.uuid4(),
            confirmed=True,
        )
        assert queued["waiting"] and not queued["observation"]["recheck_passed"]
        await session.commit()
    await finish(maker, Segments(), storage)
    async with maker() as session:
        caller = await actor(session)
        final = await invoke(session, caller, "inspect_maintenance_issue", issue_id=str(issue_id))
        assert final["observation"]["status"] == "resolved"
        assert final["observation"]["recheck_passed"]
        assert final["observation"]["requires_recheck"] is False


async def test_version_evidence_uses_live_read_projection_and_is_revocable(
    client, sessionmaker_fixture
):
    async with sessionmaker_fixture() as session:
        caller = await actor(session, USER_CONSULTANT)
        result = await invoke(
            session, caller, "inspect_knowledge_asset", asset_id=str(KA_COMPANY_L2)
        )
        assert result["observation"]["asset_id"] == str(KA_COMPANY_L2)
        assert await tools.sources_available(session, caller, result["sources"])
        asset = await session.get(KnowledgeAsset, KA_COMPANY_L2)
        asset.asset_status = "archived"
        await session.commit()
        assert not await tools.sources_available(session, caller, result["sources"])


async def test_delegated_recheck_wait_handle_cannot_read_whole_library_run(
    client,
    sessionmaker_fixture,
):
    policy = await configure(client)
    async with sessionmaker_fixture() as session:
        issue_id = await issue_fixture(session, policy["id"])
        asset = await session.get(KnowledgeAsset, KA_COMPANY_L2)
        asset.maintainer_user_id, asset.maintenance_delegated = USER_CONSULTANT, True
        await session.commit()
        caller = await actor(session, USER_CONSULTANT)
        prepared = await invoke(
            session, caller, "request_maintenance_recheck", issue_id=str(issue_id)
        )
        queued = await tools.execute(
            session,
            caller,
            "company",
            prepared["confirmation"]["arguments"],
            request_id=uuid.uuid4(),
            confirmed=True,
        )
        waiting = queued["waiting"]
        assert waiting and waiting["arguments"]["issue_id"] == str(issue_id)
        observed = await tools.execute(
            session,
            caller,
            "company",
            {"action": waiting["action"], **waiting["arguments"]},
            request_id=uuid.uuid4(),
        )
        assert observed["observation"]["total"] == 1
        await session.commit()
        boss = await actor(session)
        run = await invoke(session, boss, "start_maintenance_scan")
        # Even a targeted scan needs the issue-scoped handle for delegated viewers.
        with pytest.raises(HTTPException):
            await invoke(
                session, caller, "observe_maintenance_scan", run_id=run["observation"]["run_id"]
            )


async def test_real_runtime_resumes_after_worker_recheck_and_does_not_duplicate_write(
    client,
    sessionmaker_fixture,
    tmp_path,
    monkeypatch,
):
    maker = sessionmaker_fixture
    policy = await configure(client, content=True)
    asset_id, storage = await content_asset(maker, tmp_path, body="经过修订的知识资料和实施方法。")
    async with maker() as session:
        issue_id = await issue_fixture(session, policy["id"], asset_id=asset_id)
    model = Model(
        {"action": "inspect_maintenance_issue", "issue_id": str(issue_id)},
        {"action": "request_maintenance_recheck", "issue_id": str(issue_id)},
        {"action": "inspect_maintenance_issue", "issue_id": str(issue_id)},
        {"action": "answer", "content": "已根据真实复检结果核对。"},
    )

    async def resolve(*args, **kwargs):
        return model

    monkeypatch.setattr(runtime, "resolve_generation_llm_client", resolve)
    created = await client.post(
        "/api/v1/ai-workspace/sessions",
        headers=headers(),
        json={"request_id": str(uuid.uuid4()), "agent_key": "knowledge-maintenance"},
    )
    assert created.status_code == 201, created.text
    path = "/api/v1/ai-workspace/sessions/" + created.json()["id"]
    submitted = await client.post(
        path + "/messages",
        headers=headers(),
        json={
            "request_id": str(uuid.uuid4()),
            "content": "核对这个问题并请求复检",
            "model_ref": "system_default",
            "context_key": "company",
        },
    )
    assert submitted.status_code == 202, submitted.text
    before = (await client.get(path, headers=headers())).json()
    run = before["runs"][0]
    assert run["status"] == "awaiting_confirmation", before
    decision_id = str(uuid.uuid4())
    endpoint = f"{path}/runs/{run['id']}/actions/{run['pending_action']['id']}"
    decision = await client.post(
        endpoint, headers=headers(), json={"request_id": decision_id, "decision": "approve"}
    )
    assert decision.status_code == 202, decision.text
    waiting = (await client.get(path, headers=headers())).json()
    assert waiting["runs"][0]["status"] == "waiting", waiting
    await finish(maker, Segments(), storage)
    async with maker() as session:
        assert (await session.get(MaintenanceIssue, issue_id)).status == "resolved"
        row = await session.get(WorkspaceRun, uuid.UUID(run["id"]))
        row.next_wake_at = utc_now() - timedelta(seconds=1)
        await session.commit()
    await runtime.recover(maker)
    final = (await client.get(path, headers=headers())).json()
    assert final["runs"][0]["status"] == "completed", final
    observed = [
        entry["observation"]
        for entry in final["actions"]
        if entry["tool"] == "inspect_maintenance_issue"
    ]
    assert any(item.get("recheck_passed") for item in observed)
    assert PHONE not in json.dumps(final, ensure_ascii=False)
    assert EMAIL not in json.dumps(model.prompts, ensure_ascii=False)
    repeated = await client.post(
        endpoint, headers=headers(), json={"request_id": decision_id, "decision": "approve"}
    )
    assert repeated.status_code in {202, 409}
    async with maker() as session:
        assert await session.scalar(select(func.count()).select_from(MaintenanceRun)) == 1

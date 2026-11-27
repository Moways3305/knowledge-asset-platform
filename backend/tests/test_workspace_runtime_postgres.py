"""Real PostgreSQL races for durable action approval and side-effect fencing."""

import asyncio
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
import test_job_execution_postgres as jobs
from fastapi import HTTPException
from sqlalchemy import func, select

from app.db.utils import utc_now
from app.models.ai_workspace import WorkspaceAction, WorkspaceArtifact, WorkspaceRun
from app.schemas.ai_workspace import ActionDecision, MessageCreate, SessionCreate
from app.seed.dev_seed import USER_CONSULTANT
from app.services import ai_workspace as service
from app.services import workspace_registry as registry
from app.services.maintenance_access import actor_context

job_db = jobs.job_db


@pytest.fixture
def tools(monkeypatch):
    calls = []

    async def execute(session, caller, context, command, *, request_id, confirmed=False):
        calls.append((request_id, confirmed))
        assert confirmed
        row = await session.get(WorkspaceAction, request_id)
        session.add(
            WorkspaceArtifact(
                id=uuid.uuid5(request_id, "effect"),
                session_id=row.session_id,
                run_id=row.run_id,
                title="Domain effect",
                content="Synthetic effect",
            )
        )
        return {"observation": {"receipt_summary": "Synthetic domain effect committed"}}

    async def sources(*args):
        return True

    monkeypatch.setattr(
        registry,
        "maintenance_module",
        lambda: SimpleNamespace(
            definitions=lambda: [
                {
                    "key": "fake_write",
                    "label": "Write",
                    "description": "Synthetic write",
                    "input_schema": {},
                    "mutating": True,
                }
            ],
            execute=execute,
            sources_available=sources,
        ),
    )

    class Model:
        async def chat_completion(self, *args, **kwargs):
            return '{"action":"answer","content":"Synthetic summary"}'

    async def resolve(*args, **kwargs):
        return Model()

    monkeypatch.setattr(service, "resolve_generation_llm_client", resolve)
    return calls


async def prepared(maker, *, status="awaiting_confirmation"):
    async with maker() as session:
        caller = await actor_context(session, USER_CONSULTANT, "consultant")
        chat = await service.create_session(
            session,
            caller,
            SessionCreate(request_id=uuid.uuid4(), agent_key="knowledge-maintenance"),
        )
        created = await service.start(
            session,
            caller,
            chat.id,
            MessageCreate(
                request_id=uuid.uuid4(),
                content="Synthetic goal",
                model_ref="system_default",
                context_key="company",
            ),
        )
        run = await session.get(WorkspaceRun, created.id)
        action = WorkspaceAction(
            id=uuid.uuid4(),
            session_id=chat.id,
            run_id=run.id,
            seq=1,
            tool="fake_write",
            label="Synthetic write",
            status="awaiting_confirmation" if status == "awaiting_confirmation" else "approved",
            arguments={"action": "fake_write", "version": "v1"},
            summary="Write version v1",
        )
        session.add(action)
        run.status = status
        run.step_count = 1
        run.runtime_state = {
            "pending_action_id": str(action.id),
            "transcript": [{"role": "user", "content": "Synthetic goal"}],
        }
        if status == "running":
            run.claim, run.lease_until = uuid.uuid4(), utc_now() - timedelta(minutes=5)
        await session.commit()
        return caller, chat.id, run.id, action.id, run.claim


@pytest.mark.parametrize("same_request", [True, False])
async def test_parallel_approval_and_workers_execute_one_effect(job_db, tools, same_request):
    maker, _ = job_db
    caller, sid, rid, aid, _ = await prepared(maker)
    first = ActionDecision(request_id=uuid.uuid4(), decision="approve")
    second = first if same_request else ActionDecision(request_id=uuid.uuid4(), decision="approve")

    async def approve(command):
        async with maker() as session:
            return await service.decide_action(session, caller, sid, rid, aid, command)

    results = await asyncio.wait_for(
        asyncio.gather(approve(first), approve(second), return_exceptions=True), 10
    )
    success = [r for r in results if not isinstance(r, Exception)]
    assert len(success) == (2 if same_request else 1)
    for error in results:
        if isinstance(error, Exception):
            assert isinstance(error, HTTPException) and error.status_code == 409
    await asyncio.wait_for(
        asyncio.gather(service.execute(maker, rid), service.execute(maker, rid)), 10
    )
    assert tools == [(aid, True)]
    async with maker() as session:
        assert await session.scalar(select(func.count()).select_from(WorkspaceArtifact)) == 1
        assert (await session.get(WorkspaceRun, rid)).status == "completed"
        assert (await session.get(WorkspaceAction, aid)).status == "completed"
    assert maker.kw["bind"].pool.checkedout() == 0


async def test_stop_wins_before_tool_lock_and_prevents_domain_write(job_db, tools, monkeypatch):
    maker, _ = job_db
    caller, sid, rid, aid, claim = await prepared(maker, status="running")
    locked, release = asyncio.Event(), asyncio.Event()
    real_journal = service.journal

    async def pause_stop(session, session_id, run_id, kind, label):
        if kind == "stopped":
            locked.set()
            await release.wait()
        await real_journal(session, session_id, run_id, kind, label)

    monkeypatch.setattr(service, "journal", pause_stop)

    async def stop():
        async with maker() as session:
            return await service.stop(session, caller, sid, rid)

    stopping = asyncio.create_task(stop())
    writing = None
    try:
        await asyncio.wait_for(locked.wait(), 5)
        writing = asyncio.create_task(service.execute_pending(maker, rid, claim))
        done, _ = await asyncio.wait({writing}, timeout=0.1)
        assert not done
    finally:
        release.set()
        await asyncio.wait_for(stopping, 5)
        if writing:
            with pytest.raises(service.Stopped):
                await asyncio.wait_for(writing, 5)
    assert tools == []
    async with maker() as session:
        assert await session.scalar(select(func.count()).select_from(WorkspaceArtifact)) == 0
        assert (await session.get(WorkspaceAction, aid)).status == "approved"


async def test_expired_approved_action_recovers_and_receipt_prevents_replay(job_db, tools):
    maker, _ = job_db
    _, _, rid, aid, _ = await prepared(maker, status="running")
    await service.recover(maker)
    await service.recover(maker)
    assert tools == [(aid, True)]
    async with maker() as session:
        assert (await session.get(WorkspaceRun, rid)).status == "completed"
        assert await session.scalar(select(func.count()).select_from(WorkspaceArtifact)) == 1

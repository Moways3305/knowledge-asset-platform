"""PostgreSQL-only session serialization and late-result publication fences.

The shared fixture creates a random isolated schema on KAP_TEST_POSTGRES_URL;
it never falls back to SQLite or operates on an existing application's tables.
"""

import asyncio
import uuid
from datetime import timedelta

import pytest
import test_job_execution_postgres as jobs
from fastapi import HTTPException
from sqlalchemy import func, select

from app.db.utils import utc_now
from app.models.ai_workspace import (
    WorkspaceArtifact,
    WorkspaceEvent,
    WorkspaceMessage,
    WorkspaceRun,
    WorkspaceSession,
)
from app.schemas.ai_workspace import MessageCreate, SessionCreate
from app.seed.dev_seed import USER_CONSULTANT
from app.services import ai_workspace as service
from app.services.maintenance_access import actor_context

job_db = jobs.job_db


class Model:
    async def chat_completion(self, *args, **kwargs):
        return '{"action":"answer","content":"Synthetic answer"}'


async def conversation(maker):
    async with maker() as session:
        caller = await actor_context(session, USER_CONSULTANT, "consultant")
        row = await service.create_session(session, caller, SessionCreate(request_id=uuid.uuid4()))
        return row.id, caller


async def submit(maker, caller, session_id, command):
    async with maker() as session:
        return await service.start(session, caller, session_id, command)


@pytest.mark.parametrize("collision", ["same_request", "different_request", "changed_payload"])
async def test_parallel_submission_serializes_without_duplicate_messages(
    job_db, monkeypatch, collision
):
    maker, _ = job_db
    session_id, caller = await conversation(maker)
    first = MessageCreate(
        request_id=uuid.uuid4(), content="Synthetic first task", model_ref="system_default"
    )
    second = MessageCreate(
        request_id=uuid.uuid4() if collision == "different_request" else first.request_id,
        content="Synthetic changed task" if collision == "changed_payload" else first.content,
        model_ref="system_default",
    )
    entered = 0
    both_read_initial_state = asyncio.Event()

    async def resolve(*args, **kwargs):
        # Both independent transactions must pass the initial existence read
        # before competing for the session's conditional UPDATE.
        nonlocal entered
        entered += 1
        if entered == 2:
            both_read_initial_state.set()
        await asyncio.wait_for(both_read_initial_state.wait(), 5)
        return Model()

    monkeypatch.setattr(service, "resolve_generation_llm_client", resolve)
    results = await asyncio.wait_for(
        asyncio.gather(
            submit(maker, caller, session_id, first),
            submit(maker, caller, session_id, second),
            return_exceptions=True,
        ),
        10,
    )
    successes = [result for result in results if not isinstance(result, Exception)]
    failures = [result for result in results if isinstance(result, Exception)]
    if collision == "same_request":
        assert len(successes) == 2 and {result.id for result in successes} == {first.request_id}
        assert not failures
    else:
        assert len(successes) == len(failures) == 1
        assert isinstance(failures[0], HTTPException) and failures[0].status_code == 409
    async with maker() as check:
        assert await check.scalar(select(func.count()).select_from(WorkspaceRun)) == 1
        assert await check.scalar(select(func.count()).select_from(WorkspaceMessage)) == 1
        events = list(await check.scalars(select(WorkspaceEvent).order_by(WorkspaceEvent.seq)))
        assert [(event.seq, event.type) for event in events] == [(1, "queued")]
        row = await check.get(WorkspaceSession, session_id)
        assert row.active_run_id == successes[0].id and row.event_seq == 1


async def claimed_run(maker, caller, session_id, monkeypatch):
    async def resolve(*args, **kwargs):
        return Model()

    monkeypatch.setattr(service, "resolve_generation_llm_client", resolve)
    run = await submit(
        maker,
        caller,
        session_id,
        MessageCreate(
            request_id=uuid.uuid4(),
            content="Synthetic slow task",
            model_ref="system_default",
        ),
    )
    claim = uuid.uuid4()
    async with maker() as session:
        row = await session.get(WorkspaceRun, run.id)
        row.status, row.claim = "running", claim
        row.lease_until = utc_now() + timedelta(minutes=3)
        await session.commit()
    return run.id, claim


async def test_stop_holds_session_lock_and_fences_waiting_result(job_db, monkeypatch):
    maker, _ = job_db
    session_id, caller = await conversation(maker)
    run_id, claim = await claimed_run(maker, caller, session_id, monkeypatch)
    stopping_has_lock, release_stop = asyncio.Event(), asyncio.Event()
    real_journal = service.journal

    async def pause_before_stop_commit(session, current_session_id, current_run_id, kind, label):
        if kind == "stopped":
            stopping_has_lock.set()
            await release_stop.wait()
        await real_journal(session, current_session_id, current_run_id, kind, label)

    monkeypatch.setattr(service, "journal", pause_before_stop_commit)

    async def stop():
        async with maker() as session:
            return await service.stop(session, caller, session_id, run_id)

    stopping = asyncio.create_task(stop())
    late = None
    try:
        await asyncio.wait_for(stopping_has_lock.wait(), 5)
        # A separate PostgreSQL connection reads the old committed running row,
        # then waits on the session UPDATE locked by stop's transaction.
        late = asyncio.create_task(
            service.save_decision(
                maker,
                run_id,
                claim,
                {"action": "answer", "content": "Must not be published"},
                0,
            )
        )
        done, _ = await asyncio.wait({late}, timeout=0.1)
        assert not done, "a late result bypassed the session write lock"
    finally:
        release_stop.set()
        result = await asyncio.wait_for(stopping, 5)
        if late is not None:
            with pytest.raises(service.Stopped):
                await asyncio.wait_for(late, 5)
    assert result.status == "stopped"
    assert maker.kw["bind"].pool.checkedout() == 0
    async with maker() as check:
        row = await check.get(WorkspaceRun, run_id)
        assert row.status == "stopped" and row.claim is None
        assert (await check.get(WorkspaceSession, session_id)).active_run_id is None
        assert await check.scalar(select(func.count()).select_from(WorkspaceArtifact)) == 0
        assert await check.scalar(select(func.count()).select_from(WorkspaceMessage)) == 1
        events = list(await check.scalars(select(WorkspaceEvent).order_by(WorkspaceEvent.seq)))
        assert [(event.seq, event.type) for event in events] == [(1, "queued"), (2, "stopped")]


async def test_provider_call_releases_pool_and_stop_discards_answer(job_db, monkeypatch):
    maker, _ = job_db
    session_id, caller = await conversation(maker)
    entered, release = asyncio.Event(), asyncio.Event()

    class SlowModel:
        async def chat_completion(self, *args, **kwargs):
            entered.set()
            await release.wait()
            return '{"action":"answer","content":"Late provider answer"}'

    async def resolve(*args, **kwargs):
        return SlowModel()

    monkeypatch.setattr(service, "resolve_generation_llm_client", resolve)
    run = await submit(
        maker,
        caller,
        session_id,
        MessageCreate(
            request_id=uuid.uuid4(),
            content="Synthetic task",
            model_ref="system_default",
        ),
    )
    worker = asyncio.create_task(service.execute(maker, run.id))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert maker.kw["bind"].pool.checkedout() == 0
        async with maker() as session:
            stopped = await asyncio.wait_for(service.stop(session, caller, session_id, run.id), 3)
            assert stopped.status == "stopped"
    finally:
        release.set()
        await asyncio.wait_for(worker, 5)
    async with maker() as check:
        assert await check.scalar(select(func.count()).select_from(WorkspaceMessage)) == 1
        assert await check.scalar(select(func.count()).select_from(WorkspaceArtifact)) == 0
        assert (await check.get(WorkspaceRun, run.id)).status == "stopped"

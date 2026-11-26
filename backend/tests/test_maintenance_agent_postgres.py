"""Real independent transactions: one policy/run and revocation during model I/O."""

import asyncio

import test_job_execution_postgres as jobs
import test_maintenance_agent as fixture
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models.maintenance_agent import MaintenanceIssue, MaintenancePolicy, MaintenanceRun
from app.schemas.maintenance_agent import PolicyCommand
from app.seed.dev_seed import USER_BOSS
from app.services.maintenance_access import actor_context
from app.services.maintenance_agent import configure
from app.services.maintenance_jobs import process_one, start_run

job_db = jobs.job_db


async def test_project_version_recheck_with_foreign_keys(job_db, client, tmp_path, monkeypatch):
    import test_maintenance_continuity as continuity

    from app.db.session import get_db
    from app.main import app

    maker, _ = job_db

    async def database():
        async with maker() as session:
            yield session

    monkeypatch.setitem(app.dependency_overrides, get_db, database)
    await continuity.project_version_workflow(client, maker, tmp_path, prescanned=True)


async def save(maker, revision=0):
    async with maker() as session:
        caller = await actor_context(session, USER_BOSS, "boss")
        return await configure(
            session,
            caller,
            "company",
            PolicyCommand(expected_revision=revision, content_authorized=True),
            "synthetic-maintenance",
        )


async def test_concurrent_first_configuration_has_one_winner(job_db):
    maker, _ = job_db
    results = await asyncio.gather(save(maker), save(maker), return_exceptions=True)
    assert len([x for x in results if not isinstance(x, Exception)]) == 1
    failure = next(x for x in results if isinstance(x, Exception))
    assert isinstance(failure, HTTPException) and failure.status_code == 409
    async with maker() as session:
        assert await session.scalar(select(func.count()).select_from(MaintenancePolicy)) == 1


async def test_concurrent_manual_requests_share_run(job_db):
    maker, _ = job_db
    await save(maker)

    async def request():
        async with maker() as session:
            policy = await session.scalar(select(MaintenancePolicy).with_for_update())
            run = await start_run(session, policy)
            await session.commit()
            return run.id

    assert len(set(await asyncio.gather(request(), request()))) == 1


async def test_revoke_during_external_call_is_nonblocking_and_fenced(job_db):
    maker, storage = job_db
    await save(maker)
    asset_id, storage = await fixture.content_asset(maker, storage.root)
    await fixture.run_asset(maker, asset_id)
    entered, release = asyncio.Event(), asyncio.Event()

    class Model:
        async def chat_completion(self, *args, **kwargs):
            entered.set()
            await release.wait()
            return '{"complete":true,"findings":[]}'

    task = asyncio.create_task(process_one(maker, storage=storage, client=Model()))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert not await asyncio.wait_for(process_one(maker, storage=storage, client=Model()), 3)
        await asyncio.wait_for(save(maker, revision=1), 3)
    finally:
        release.set()
        await task
    async with maker() as session:
        assert await session.scalar(select(func.count()).select_from(MaintenanceIssue)) == 0
        run = await session.scalar(select(MaintenanceRun))
        assert run.status == "cancelled"

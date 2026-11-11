"""Real row locks, crash recovery, and transaction release for governance scans."""

import asyncio

import pytest
import test_governance_scan_batches as helpers
import test_job_execution_postgres as jobs
from sqlalchemy import select

from app.models.governance_scan import GovernanceScanRun
from app.models.knowledge import KnowledgeAsset
from app.services import knowledge_review
from app.services.jobs import governance_scan, lifecycle_scan

job_db = jobs.job_db
kind = helpers.kind


async def test_locked_asset_is_not_lost_while_later_assets_progress(job_db, kind):
    sessions, _ = job_db
    async with sessions() as setup:
        ids = await helpers.seed(setup)
    async with sessions() as editor:
        await editor.scalar(
            select(KnowledgeAsset).where(KnowledgeAsset.id == ids[0]).with_for_update()
        )
        async with sessions() as worker:
            assert await helpers.scan(worker, kind) == 2
            assert await helpers.scan(worker, kind, resume_only=True) == 2
            assert await helpers.scan(worker, kind, resume_only=True) == 0
            assert await governance_scan.has_pending(worker)
            assert (await helpers.facts(worker, ids))["outbox"] == 4
        await editor.rollback()
    async with sessions() as worker:
        assert await helpers.drain(worker, kind) == [1]
        assert (await helpers.facts(worker, ids))["outbox"] == 5


async def test_overlap_is_nonblocking_and_cannot_duplicate_batch(job_db, kind, monkeypatch):
    sessions, _ = job_db
    async with sessions() as setup:
        ids = await helpers.seed(setup, 2)
    target = lifecycle_scan if kind == "archive" else knowledge_review.operation_events
    name = "_emit" if kind == "archive" else "publish_knowledge_trust"
    original = getattr(target, name)
    entered, release = asyncio.Event(), asyncio.Event()

    async def block(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(target, name, block)

    async def run():
        async with sessions() as session:
            return await helpers.scan(session, kind)

    task = asyncio.create_task(run())
    try:
        await asyncio.wait_for(entered.wait(), 3)
        assert await asyncio.wait_for(asyncio.gather(*(run() for _ in range(4))), 3) == [0] * 4
    finally:
        release.set()
        assert await task == 2
    async with sessions() as check:
        assert (await helpers.facts(check, ids))["outbox"] == 2


async def test_cancel_in_first_batch_is_durable_and_resume_releases_connections(
    job_db, kind, monkeypatch
):
    sessions, _ = job_db
    async with sessions() as setup:
        ids = await helpers.seed(setup, 3)
    target = lifecycle_scan if kind == "archive" else knowledge_review.operation_events
    name = "_emit" if kind == "archive" else "publish_knowledge_trust"
    original = getattr(target, name)
    entered = asyncio.Event()

    async def lost(*args, **kwargs):
        await original(*args, **kwargs)
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(target, name, lost)

    async def run():
        async with sessions() as session:
            await helpers.scan(session, kind)

    task = asyncio.create_task(run())
    await asyncio.wait_for(entered.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    monkeypatch.setattr(target, name, original)
    async with sessions() as worker:
        assert (await helpers.facts(worker, ids))["outbox"] == 0
        assert await helpers.scan(worker, kind, resume_only=True) == 2
        assert sessions.kw["bind"].pool.checkedout() == 0
        # Separate editor can lock every asset between batches.
        async with sessions() as editor:
            assert (
                len(
                    list(
                        await editor.scalars(
                            select(KnowledgeAsset)
                            .where(KnowledgeAsset.id.in_(ids))
                            .with_for_update(nowait=True)
                        )
                    )
                )
                == 3
            )
            await editor.rollback()
        assert await helpers.scan(worker, kind, resume_only=True) == 1
        assert (await helpers.facts(worker, ids))["outbox"] == 3
        run = await worker.get(GovernanceScanRun, kind)
        assert run.completed_at is not None

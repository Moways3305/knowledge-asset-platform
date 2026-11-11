"""Independent PostgreSQL transactions for duplicate reuse scans and child loss."""

import asyncio

import pytest
import test_job_execution_postgres as jobs
import test_reuse_scan_batches as helpers
from sqlalchemy import select

from app.models.knowledge import KnowledgeAsset
from app.services.jobs import governance_scan, reuse_upgrade

job_db = jobs.job_db
batches = helpers.batches


async def test_locked_asset_remains_pending_and_other_assets_progress(job_db):
    sessions, _ = job_db
    async with sessions() as setup:
        ids = await helpers.seed(setup)
    async with sessions() as editor:
        await editor.scalar(
            select(KnowledgeAsset).where(KnowledgeAsset.id == ids[0]).with_for_update()
        )
        async with sessions() as worker:
            assert (await reuse_upgrade.scan_reuse_and_recommend(worker))["assets"] == 2
            assert (await reuse_upgrade.scan_reuse_and_recommend(worker, resume_only=True))[
                "assets"
            ] == 2
            assert (await reuse_upgrade.scan_reuse_and_recommend(worker, resume_only=True))[
                "assets"
            ] == 0
            assert await governance_scan.has_pending(worker, ("reuse",))
            assert await helpers.facts(worker, ids) == (4, 8)
        await editor.rollback()
    async with sessions() as worker:
        assert (await helpers.drain(worker))[0]["assets"] == 1
        assert await helpers.facts(worker, ids) == (5, 10)


async def test_overlap_does_not_depend_on_usage_update_lock(job_db, monkeypatch):
    sessions, _ = job_db
    async with sessions() as setup:
        # Existing telemetry already newer: old code's incidental UPDATE lock
        # would never be acquired, so check-then-insert was unsafe in this case.
        ids = await helpers.seed(setup, 2, usage_current=True)
    original = reuse_upgrade.audit_service.record_system_event
    entered, release = asyncio.Event(), asyncio.Event()

    async def block(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(reuse_upgrade.audit_service, "record_system_event", block)

    async def run():
        async with sessions() as session:
            return await reuse_upgrade.scan_reuse_and_recommend(session)

    task = asyncio.create_task(run())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        others = await asyncio.wait_for(asyncio.gather(*(run() for _ in range(4))), 5)
        assert all(r == {"assets": 0, "recommended": 0, "usage_updated": 0} for r in others)
    finally:
        release.set()
        result = await task
        assert result == {"assets": 2, "recommended": 2, "usage_updated": 0}
    async with sessions() as check:
        assert await helpers.facts(check, ids) == (2, 4)


async def test_cancelled_first_batch_resumes_without_duplicate_effects_or_connections(
    job_db,
    monkeypatch,
):
    sessions, _ = job_db
    async with sessions() as setup:
        ids = await helpers.seed(setup, 3)
    original = governance_scan.finish_batch
    entered = asyncio.Event()

    async def lost(*_args, **_kwargs):
        # Usage UPDATE and staged audit/outbox all exist, but no commit yet.
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(governance_scan, "finish_batch", lost)

    async def run():
        async with sessions() as session:
            await reuse_upgrade.scan_reuse_and_recommend(session)

    task = asyncio.create_task(run())
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    monkeypatch.setattr(governance_scan, "finish_batch", original)
    assert sessions.kw["bind"].pool.checkedout() == 0
    async with sessions() as worker:
        assert await helpers.facts(worker, ids) == (0, 0)
        assert await governance_scan.has_pending(worker, ("reuse",))
        assert (await reuse_upgrade.scan_reuse_and_recommend(worker, resume_only=True))[
            "assets"
        ] == 2
        assert sessions.kw["bind"].pool.checkedout() == 0
        async with sessions() as editor:
            assets = list(
                await editor.scalars(
                    select(KnowledgeAsset)
                    .where(KnowledgeAsset.id.in_(ids))
                    .with_for_update(nowait=True)
                )
            )
            assert len(assets) == 3
            assert sum(a.last_called_at is not None for a in assets) == 2
            await editor.rollback()
        assert (await helpers.drain(worker))[0]["assets"] == 1
        assert await helpers.facts(worker, ids) == (3, 6)

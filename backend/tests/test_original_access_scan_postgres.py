"""Real row locks, administrative changes and lost-transaction scan recovery."""

import asyncio

import pytest
import test_job_execution_postgres as jobs
import test_original_access_scan as helpers
from sqlalchemy import select, update

from app.db.utils import utc_now
from app.models.identity import User
from app.models.knowledge import KnowledgeAsset
from app.models.original_access import AccessGrant, OriginalAccessRequest
from app.models.permission_rule import PermissionRule
from app.seed.dev_seed import USER_BOSS, USER_CONSULTANT
from app.services import original_access
from app.services.jobs import original_access_scan as scan

job_db = jobs.job_db
scan_setup = helpers.scan_setup


@pytest.mark.parametrize("kind", ["asset", "request", "grant", "identity"])
async def test_locked_item_does_not_block_later_work_and_returns_next_cycle(job_db, kind):
    sessions, _ = job_db
    async with sessions() as setup:
        ids, assets = await helpers.seed(setup, 0, 3)
        if kind == "grant":
            setup.add(
                AccessGrant(
                    asset_id=assets[0],
                    grantee_user_id=USER_CONSULTANT,
                    granted_by_user_id=USER_BOSS,
                    expires_at=utc_now(),
                )
            )
            await setup.commit()
    models = {
        "asset": (KnowledgeAsset, KnowledgeAsset.id == assets[0]),
        "request": (OriginalAccessRequest, OriginalAccessRequest.id == ids[0]),
        "grant": (AccessGrant, AccessGrant.asset_id == assets[0]),
        "identity": (User, User.id == USER_CONSULTANT),
    }
    model, condition = models[kind]
    async with sessions() as editor:
        await editor.execute(select(model).where(condition).with_for_update())
        async with sessions() as worker:
            result = await asyncio.wait_for(helpers.run(worker), 3)
            assert result["deferred_locked"] == (3 if kind == "identity" else 1)
            assert result["approved"] == (0 if kind == "identity" else 2)
            assert result["errors"] == 0
            assert (await helpers.run(worker, resume_only=True))["checked"] == 0
        await editor.rollback()
    async with sessions() as worker:
        assert (await helpers.run(worker))["approved"] == (3 if kind == "identity" else 1)
        grants, audits, events = await helpers.counts(worker, ids, assets)
        assert grants == (4 if kind == "grant" else 3)
        assert audits == events == 3


async def test_overlapping_workers_cannot_duplicate_decisions(job_db, monkeypatch):
    sessions, _ = job_db
    async with sessions() as setup:
        ids, assets = await helpers.seed(setup, 0, 3)
    original = scan._commit_item
    entered, release = asyncio.Event(), asyncio.Event()

    async def block(session, run, key):
        if key[1] == ids[0]:
            entered.set()
            await release.wait()
        await original(session, run, key)

    monkeypatch.setattr(scan, "_commit_item", block)

    async def run():
        async with sessions() as worker:
            return await helpers.run(worker)

    task = asyncio.create_task(run())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        others = await asyncio.wait_for(asyncio.gather(*(run() for _ in range(4))), 3)
        assert all(r["checked"] == r["approved"] == 0 for r in others)
    finally:
        release.set()
        assert (await task)["approved"] == 3
    async with sessions() as check:
        assert await helpers.counts(check, ids, assets) == (3, 3, 3)


@pytest.mark.parametrize("interrupted_index", [0, 1])
async def test_cancelled_decision_resumes_after_committed_predecessors(
    job_db, monkeypatch, interrupted_index
):
    sessions, _ = job_db
    async with sessions() as setup:
        ids, assets = await helpers.seed(setup, 0, 3)
    original = scan._commit_item
    entered = asyncio.Event()

    async def lose(session, run, key):
        if key[1] == ids[interrupted_index]:
            entered.set()
            await asyncio.Event().wait()
        await original(session, run, key)

    monkeypatch.setattr(scan, "_commit_item", lose)

    async def run():
        async with sessions() as worker:
            await helpers.run(worker)

    task = asyncio.create_task(run())
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sessions.kw["bind"].pool.checkedout() == 0
    monkeypatch.setattr(scan, "_commit_item", original)
    async with sessions() as worker:
        assert await helpers.counts(worker, ids, assets) == (interrupted_index,) * 3
        assert (await helpers.run(worker, resume_only=True))["approved"] == 3 - interrupted_index
        assert sessions.kw["bind"].pool.checkedout() == 0
        assert await helpers.counts(worker, ids, assets) == (3, 3, 3)
    async with sessions() as editor:
        assert (
            len(
                list(
                    await editor.scalars(
                        select(KnowledgeAsset)
                        .where(KnowledgeAsset.id.in_(assets))
                        .with_for_update(nowait=True)
                    )
                )
            )
            == 3
        )


@pytest.mark.parametrize("edit", ["disable_rule", "deactivate_user"])
async def test_admin_change_serializes_with_current_decision_and_blocks_later_ones(
    job_db,
    monkeypatch,
    edit,
):
    sessions, _ = job_db
    async with sessions() as setup:
        ids, assets = await helpers.seed(setup, 0, 3)
    original = scan._commit_item
    entered, release, editing = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def block(session, run, key):
        entered.set()
        await release.wait()
        await original(session, run, key)

    monkeypatch.setattr(scan, "_commit_item", block)

    async def first():
        async with sessions() as worker:
            return await helpers.run(worker, limit=1)

    async def change():
        async with sessions() as admin:
            editing.set()
            statement = (
                update(PermissionRule)
                .where(PermissionRule.rule_key == helpers.TIMEOUT)
                .values(enabled=False)
                if edit == "disable_rule"
                else update(User).where(User.id == USER_CONSULTANT).values(status="inactive")
            )
            await admin.execute(statement)
            await admin.commit()

    task = asyncio.create_task(first())
    await asyncio.wait_for(entered.wait(), 5)
    edit_task = asyncio.create_task(change())
    try:
        await editing.wait()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(edit_task), 0.2)
    finally:
        release.set()
        assert (await task)["approved"] == 1
        await asyncio.wait_for(edit_task, 5)
    monkeypatch.setattr(scan, "_commit_item", original)
    async with sessions() as worker:
        assert (await helpers.run(worker, resume_only=True))["approved"] == 0
        assert await helpers.counts(worker, ids, assets) == (1, 1, 1)


async def test_human_rejection_wins_while_scanner_defers_locked_request(job_db):
    from test_original_access_state_conflicts import reviewer

    sessions, _ = job_db
    async with sessions() as setup:
        ids, assets = await helpers.seed(setup, 0, 2)
    async with sessions() as human:
        await original_access._lock_request(human, ids[0])
        async with sessions() as worker:
            result = await asyncio.wait_for(helpers.run(worker), 3)
            assert result["deferred_locked"] == result["approved"] == 1
        await original_access.reject_request(human, reviewer(), ids[0], "human refusal", "human")
    async with sessions() as worker:
        assert (await helpers.run(worker))["approved"] == 0
        assert (await worker.get(OriginalAccessRequest, ids[0])).status == "rejected"
        assert not await worker.scalar(
            select(AccessGrant.id).where(AccessGrant.asset_id == assets[0])
        )

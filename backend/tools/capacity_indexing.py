"""Synthetic indexing worker connection probe for compose.capacity-test.yml only.

Run after capacity_probe.py seed. Each run creates disposable assets with canonical
Markdown, enqueues real Celery jobs and observes PostgreSQL during controlled HTTP
waits. Pair --stage models/upload across revisions; --stage initialize also checks
concurrent first use of one personal KB. Reports stay in /capacity, outside git.
"""

import argparse
import asyncio
import hashlib
import time
import uuid

import httpx
from capacity_common import FIXTURE, email, guard
from capacity_probe import save
from sqlalchemy import delete, select, text

guard()
from app.db.session import get_engine, get_sessionmaker  # noqa: E402
from app.models.identity import User  # noqa: E402
from app.models.indexing_job import IndexingOperationJob  # noqa: E402
from app.models.knowledge import (  # noqa: E402
    KnowledgeAsset,
    KnowledgeAssetFileObject,
    KnowledgeAssetVersion,
)
from app.models.weknora import WeknoraKbMapping  # noqa: E402
from app.services.storage import get_storage  # noqa: E402
from app.worker.tasks.indexing import run_indexing_operation  # noqa: E402


async def make_jobs(assets):
    ids = []
    async with get_sessionmaker()() as session:
        for asset_id in assets:
            job = IndexingOperationJob(
                operation_type="retry_index",
                status="queued",
                target_asset_id=asset_id,
                scope_filter={"limit": 1},
                trace_id="synthetic-index-capacity",
            )
            session.add(job)
            await session.flush()
            ids.append(job.id)
        await session.commit()
    return ids


async def seed(count, missing_kb):
    assets = []
    async with get_sessionmaker()() as session:
        user = await session.scalar(select(User).where(User.email == email(98)))
        assert user is not None
        if missing_kb:
            await session.execute(
                delete(WeknoraKbMapping).where(
                    WeknoraKbMapping.scope == "personal",
                    WeknoraKbMapping.owner_user_id == user.id,
                )
            )
        for _ in range(count):
            aid, vid = uuid.uuid4(), uuid.uuid4()
            content = f"# Synthetic index test\n\n{aid}".encode()
            ref = get_storage().save(content, original_name="synthetic.canonical.md")
            session.add(
                KnowledgeAsset(
                    id=aid,
                    title="Synthetic index capacity material",
                    scope="personal",
                    zone="material",
                    asset_type="document",
                    owner_user_id=user.id,
                    current_version_id=vid,
                    visibility="private",
                    confidentiality_level="L2",
                    ai_access_level="A1",
                )
            )
            session.add(
                KnowledgeAssetVersion(
                    id=vid,
                    asset_id=aid,
                    version_no="V1",
                    version_status="active",
                    created_by=user.id,
                    index_status="index_failed",
                    directory_key="personal.learning_notes",
                )
            )
            await session.flush()
            session.add(
                KnowledgeAssetFileObject(
                    asset_id=aid,
                    version_id=vid,
                    file_variant="canonical_markdown",
                    file_name="synthetic.canonical.md",
                    file_mime_type="text/markdown",
                    file_size=len(content),
                    storage_ref=ref,
                    file_hash=hashlib.sha256(content).hexdigest(),
                    confidentiality_level="L2",
                )
            )
            assets.append(aid)
        await session.commit()
    return assets


async def execute(c, ids):
    for jid in ids:
        run_indexing_operation.apply_async(args=[str(jid)], queue="default")
    samples = []
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        fixture = (await c.get(FIXTURE + "/control")).json()
        async with get_sessionmaker()() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            "SELECT state, count(*) AS connections, "
                            "count(*) FILTER (WHERE EXISTS (SELECT 1 FROM pg_locks l "
                            "WHERE l.pid=a.pid AND l.locktype='advisory' AND l.granted)) "
                            "AS lock_owners FROM pg_stat_activity a "
                            "WHERE application_name='kap-capacity-worker' "
                            "AND datname=current_database() GROUP BY state"
                        )
                    )
                )
                .mappings()
                .all()
            )
            jobs = list(
                await session.scalars(
                    select(IndexingOperationJob).where(IndexingOperationJob.id.in_(ids))
                )
            )
            states = [
                {"status": j.status, "success": j.success_count, "failed": j.failed_count}
                for j in jobs
            ]
        samples.append({"inflight": fixture["inflight"], "connections": [dict(r) for r in rows]})
        if all(j["status"] not in {"queued", "running"} for j in states):
            return states, samples
        await asyncio.sleep(0.1)
    raise RuntimeError("Synthetic index jobs did not finish within the observation deadline")


async def run(args):
    assert 1 <= args.count <= 16 and 0 <= args.delay <= 10
    assets = await seed(args.count, args.stage == "initialize")
    ids = await make_jobs(assets)
    controls = {f"{stage}_delay": 0 for stage in ("models", "create", "initialize", "upload")}
    controls[args.stage + "_delay"] = args.delay
    controls["initialize_failures"] = 1 if args.fail_initialize else 0
    async with httpx.AsyncClient(trust_env=False, timeout=15) as c:
        before = (await c.post(FIXTURE + "/control", json=controls)).json()
        states, samples = await execute(c, ids)
        failed = sum(s["failed"] for s in states)
        if args.fail_initialize:
            assert failed == 1, states
            await c.post(FIXTURE + "/control", json={"initialize_failures": 0})
            retry_states, retry_samples = await execute(c, await make_jobs(assets))
            samples.extend(retry_samples)
            assert not any(s["failed"] for s in retry_states), retry_states
        else:
            assert all(s["status"] == "completed" and s["success"] == 1 for s in states), states
        async with get_sessionmaker()() as session:
            versions = list(
                await session.scalars(
                    select(KnowledgeAssetVersion).where(KnowledgeAssetVersion.asset_id.in_(assets))
                )
            )
            assert all(v.index_status == "indexed" for v in versions)
            mappings = list(
                await session.scalars(
                    select(WeknoraKbMapping).where(
                        WeknoraKbMapping.scope == "personal",
                        WeknoraKbMapping.owner_user_id
                        == select(User.id).where(User.email == email(98)).scalar_subquery(),
                    )
                )
            )
            mapping_count = len(mappings)
        after = (await c.get(FIXTURE + "/control")).json()
        # Terminal duplicate deliveries must not repeat any provider operation.
        await execute(c, ids)
        await asyncio.sleep(1)
        duplicates = (await c.get(FIXTURE + "/control")).json()
        assert duplicates["counts"] == after["counts"]
        delta = {k: v - before["counts"].get(k, 0) for k, v in after["counts"].items()}
        if args.stage == "initialize":
            assert mapping_count == 1 and delta.get("create") == 1, (mapping_count, delta)
        assert delta.get("upload") == args.count, delta
        save(
            "indexing-" + args.label,
            {
                "synthetic_only": True,
                "label": args.label,
                "stage": args.stage,
                "delay": args.delay,
                "count": args.count,
                "initial_failures": failed,
                "all_indexed": True,
                "duplicate_delivery_no_provider_calls": True,
                "mapping_count": mapping_count,
                "provider_calls": delta,
                "samples": samples,
            },
        )
        await c.post(FIXTURE + "/control", json={key: 0 for key in controls})


async def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--label", required=True)
    p.add_argument("--stage", choices=["models", "upload", "initialize"], required=True)
    p.add_argument("--count", type=int, default=4)
    p.add_argument("--delay", type=float, default=2)
    p.add_argument("--fail-initialize", action="store_true")
    args = p.parse_args()
    assert not args.fail_initialize or args.stage == "initialize"
    try:
        await run(args)
    finally:
        await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())

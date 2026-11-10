"""Synthetic Celery/PostgreSQL parse backlog probe; isolated compose only.

Run after capacity_probe.py seed. Compare fairness/transport with --baseline on
the previous revision. The fixed revision must also pass budget and concurrent.
Report files are written to /capacity, never committed. No provider credentials.
"""

import argparse
import asyncio
import time
import uuid

import httpx
from capacity_common import FIXTURE, email, guard
from capacity_probe import save
from sqlalchemy import select, text, update

guard()
from app.db.session import get_engine, get_sessionmaker  # noqa: E402
from app.models.identity import User  # noqa: E402
from app.models.indexing_job import OpsReconcileHeartbeat  # noqa: E402
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion  # noqa: E402
from app.worker.tasks.parse import reconcile_parse  # noqa: E402


async def seed(scenario):
    count = (
        250
        if scenario == "fairness"
        else 4
        if scenario == "budget"
        else 8
        if scenario == "concurrent"
        else 2
    )
    ids, docs = [], []
    base = uuid.uuid4().int & ~0xFFFF
    async with get_sessionmaker()() as session:
        actor = await session.scalar(select(User.id).where(User.email == email(97)))
        assert actor is not None
        for i in range(count):
            aid, vid = uuid.uuid4(), uuid.UUID(int=base + i)
            doc = "capacity-parse-" + vid.hex
            session.add(
                KnowledgeAsset(
                    id=aid,
                    title="Synthetic parse backlog",
                    scope="company",
                    zone="material",
                    asset_type="document",
                    owner_user_id=actor,
                    current_version_id=vid,
                    visibility="public",
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
                    created_by=actor,
                    index_status="indexing",
                    weknora_kb_id="capacity-company",
                    weknora_doc_id=doc,
                    weknora_parse_status="processing",
                )
            )
            ids.append(vid)
            docs.append(
                {
                    "id": doc,
                    "knowledge_base_id": "capacity-company",
                    "parse_status": "processing"
                    if scenario == "fairness" and i < 200
                    else "completed",
                    "synthetic_delay": 11
                    if scenario == "budget"
                    else 2
                    if scenario == "transport" and i == 0
                    else 0.2
                    if scenario == "concurrent"
                    else 0,
                }
            )
        await session.commit()
    return ids, docs


async def execute(c, count=1):
    deliveries = [reconcile_parse.apply_async(queue="default") for _ in range(count)]
    samples = []
    started = time.monotonic()
    while time.monotonic() - started < 60:
        control = (await c.get(FIXTURE + "/control")).json()
        async with get_sessionmaker()() as session:
            connections = await session.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                    "AND application_name='kap-capacity-worker'"
                )
            )
        samples.append(
            {
                "elapsed": round(time.monotonic() - started, 3),
                "connections": connections,
                "http_inflight": control["inflight"].get("parse", 0),
            }
        )
        if all(delivery.ready() for delivery in deliveries):
            return {
                "successful": all(d.successful() for d in deliveries),
                "seconds": round(time.monotonic() - started, 3),
                "samples": samples,
            }
        await asyncio.sleep(0.05)
    raise RuntimeError("Isolated reconciliation exceeded the observation deadline")


async def state(ids):
    async with get_sessionmaker()() as session:
        rows = list(
            await session.scalars(
                select(KnowledgeAssetVersion).where(KnowledgeAssetVersion.id.in_(ids))
            )
        )
        heartbeat = await session.scalar(
            select(OpsReconcileHeartbeat)
            .order_by(OpsReconcileHeartbeat.observed_at.desc())
            .limit(1)
        )
        return {
            "indexed": sum(r.index_status == "indexed" for r in rows),
            "failures": sum(r.index_reconcile_failure_count for r in rows),
            "active_leases": sum(r.parse_reconcile_token is not None for r in rows),
            "heartbeat": {
                k: getattr(heartbeat, k) for k in ("processed", "updated", "failed", "duration_ms")
            }
            if heartbeat
            else None,
        }


async def run(args):
    assert not args.baseline or args.scenario in {"fairness", "transport"}
    ids, docs = await seed(args.scenario)
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=10) as c:
            response = await c.post(FIXTURE + "/seed", json={"docs": docs, "kbs": []})
            response.raise_for_status()
            rounds = []
            if args.scenario == "fairness":
                for _ in range(2):
                    result = await execute(c)
                    result["state"] = await state(ids)
                    rounds.append(result)
                assert all(r["successful"] for r in rounds)
                assert rounds[-1]["state"]["indexed"] == (0 if args.baseline else 50)
            else:
                result = await execute(c, 2 if args.scenario == "concurrent" else 1)
                result["state"] = await state(ids)
                rounds.append(result)
                if args.baseline:
                    assert not result["successful"] and result["state"]["indexed"] == 0
                elif args.scenario == "transport":
                    assert (
                        result["successful"]
                        and result["state"]["indexed"] == 1
                        and result["state"]["failures"] == 1
                    )
                elif args.scenario == "budget":
                    assert result["successful"] and result["seconds"] < 25
                    assert result["state"]["failures"] == 1 and result["state"]["indexed"] == 0
                else:
                    assert result["successful"] and result["state"]["indexed"] == len(ids)
                assert result["state"]["active_leases"] == 0
            control = (await c.get(FIXTURE + "/control")).json()
            counts = [control["parse_calls"].get(d["id"], 0) for d in docs]
            peak = max(control["parse_peak"].get(d["id"], 0) for d in docs)
            assert peak <= 1
            if args.scenario == "concurrent":
                assert counts == [1] * len(ids), counts
            if not args.baseline and args.scenario in {"transport", "budget"}:
                # Clear the synthetic fault; previously unobserved work should be
                # polled before the attempted prefix, then everything converges.
                for d in docs:
                    d["synthetic_delay"] = 0
                await c.post(FIXTURE + "/seed", json={"docs": docs, "kbs": []})
                recovery = await execute(c)
                recovery["state"] = await state(ids)
                rounds.append(recovery)
                assert recovery["successful"] and recovery["state"]["indexed"] == len(ids)
                assert recovery["state"]["failures"] == 0
            save(
                "parse-" + args.label,
                {
                    "synthetic_only": True,
                    "scenario": args.scenario,
                    "baseline": args.baseline,
                    "documents": len(ids),
                    "rounds": rounds,
                    "calls_per_document": counts,
                    "peak_requests_per_document": peak,
                    "expected_behavior_verified": True,
                },
            )
    finally:
        # Retire this disposable case from the scanner before the next scenario.
        async with get_sessionmaker()() as session:
            await session.execute(
                update(KnowledgeAssetVersion)
                .where(KnowledgeAssetVersion.id.in_(ids))
                .values(weknora_parse_status="completed", index_status="indexed")
            )
            await session.commit()


async def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--label", required=True)
    p.add_argument(
        "--scenario", choices=["fairness", "transport", "budget", "concurrent"], required=True
    )
    p.add_argument("--baseline", action="store_true")
    args = p.parse_args()
    try:
        await run(args)
    finally:
        await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())

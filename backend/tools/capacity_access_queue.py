"""Isolated real-consumer access fairness, ordinary queue traffic and child loss."""

import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path

import capacity_metrics  # noqa: F401
import httpx
from capacity_access import facts, seed
from capacity_common import DATABASE, guard
from capacity_parse_queue import wait_results, worker_metrics
from capacity_probe import client, distribution, login, save
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

guard()

from app.models.notification import BusinessNotification  # noqa: E402
from app.models.outbox import DomainEventOutbox  # noqa: E402
from app.worker.celery_app import celery_app  # noqa: E402

TASK = "access.auto_approve_timed_out"


async def pending(maker):
    async with maker() as session:
        return await session.scalar(
            text(
                "SELECT count(*) FROM governance_scan_runs WHERE name='original_access' AND completed_at IS NULL"
            )
        )


async def drain(maker, ids, assets, phase, expected):
    for _ in range(900):
        if phase == "baseline" or not await pending(maker):
            break
        await asyncio.sleep(0.2)
    else:
        raise AssertionError("Access continuation stalled")
    # No beat here: explicit outbox drains start after ordinary-task timing.
    # This verifies notification facts, not production notification latency.
    await wait_results(
        [
            celery_app.send_task("domain_events.dispatch_pending")
            for _ in range(max(1, (expected + 99) // 100))
        ],
        timeout=180,
    )
    async with maker() as session:
        assert not await session.scalar(
            select(func.count())
            .select_from(DomainEventOutbox)
            .where(DomainEventOutbox.aggregate_id.in_(ids), DomainEventOutbox.status != "completed")
        )
        notices = await session.scalar(
            select(func.count())
            .select_from(BusinessNotification)
            .where(
                BusinessNotification.target_id.in_(ids),
                BusinessNotification.event_type == "original_access.decided",
            )
        )
    result = await facts(maker, ids, assets)
    assert result["grants"] == result["outbox"] == result["audits"] == notices == expected, result
    assert result["confidential_grants"] == 0 and result["business_assets_unchanged"] == len(assets)
    result["notifications"] = notices
    return result


async def queue(args, maker):
    async with client() as http:
        for _ in range(60):
            try:
                if (await http.get("/api/v1/knowledge")).status_code == 401:
                    break
            except httpx.TransportError:
                pass
            await asyncio.sleep(1)
        else:
            raise AssertionError("Isolated API did not become ready")
    ids, assets = await seed(maker, args.blocked, args.eligible)
    async with maker() as session:
        await session.execute(update(DomainEventOutbox).values(status="completed"))
        await session.commit()
    start = time.time()
    latencies, statuses = [], {}
    stop = asyncio.Event()

    async def traffic():
        async with client() as http:
            await login(http, 0)
            while not stop.is_set():
                before = time.monotonic()
                response = await http.get(
                    "/api/v1/knowledge",
                    params={
                        "scope": "company",
                        "directory_key": "company.introduction",
                        "page": 1,
                        "page_size": 20,
                    },
                )
                latencies.append(time.monotonic() - before)
                statuses[str(response.status_code)] = statuses.get(str(response.status_code), 0) + 1
                assert response.status_code == 200 and len(response.json()["items"]) == 20
                await asyncio.sleep(0.05)

    task = asyncio.create_task(traffic())
    try:
        scans = [celery_app.send_task(TASK) for _ in range(2)]
        await asyncio.sleep(0.15)
        markers = [
            celery_app.send_task(name)
            for name in (
                "ops.worker_heartbeat",
                "ingest.recover_orphans",
                "indexing.recover_interrupted_jobs",
            )
        ]
        marker_wait = asyncio.create_task(wait_results(markers, timeout=180))
        await wait_results(scans, timeout=180)
        marker_seconds = await marker_wait
        result = await drain(
            maker, ids, assets, args.phase, args.eligible if args.phase == "fixed" else 0
        )
    finally:
        stop.set()
        await task
    save(
        f"access-queue-{args.phase}",
        {
            "passed": True,
            "phase": args.phase,
            "synthetic_only": True,
            "production_changed": False,
            "skippable_prefix": args.blocked,
            "eligible_tail": args.eligible,
            "ordinary_task_group_seconds": marker_seconds,
            "list_requests": len(latencies),
            "list_statuses": statuses,
            "list_latency": distribution(latencies),
            **result,
            "worker_metrics": worker_metrics(start),
        },
    )


async def crash(args, maker):
    control, ready = Path("/capacity/access-pause"), Path("/capacity/access-paused.json")
    record = Path("/capacity/access-crash-private.json")
    if args.mode == "crash-prepare":
        assert not await pending(maker)
        ids, assets = await seed(maker, 0, 5)
        ready.unlink(missing_ok=True)
        control.write_text(str(ids[1]))  # First commits; second loses its transaction.
        delivery = celery_app.send_task(TASK)
        record.write_text(
            json.dumps(
                {
                    "ids": list(map(str, ids)),
                    "assets": list(map(str, assets)),
                    "task_id": delivery.id,
                }
            )
        )
        for _ in range(300):
            if ready.exists():
                save("access-crash-ready", json.loads(ready.read_text()))
                return
            await asyncio.sleep(0.1)
        control.unlink(missing_ok=True)
        raise AssertionError("Consumer did not pause before the second decision commit")
    assert not control.exists(), "Kill the isolated child and remove the fault first"
    saved = json.loads(record.read_text())
    ids, assets = ([uuid.UUID(v) for v in saved[key]] for key in ("ids", "assets"))
    delivery = celery_app.AsyncResult(saved["task_id"])
    for _ in range(100):
        if delivery.ready():
            break
        await asyncio.sleep(0.1)
    assert delivery.state == "FAILURE"
    before = await facts(maker, ids, assets)
    assert before["grants"] == before["audits"] == before["outbox"] == 1, before
    await wait_results([celery_app.send_task(TASK, kwargs={"resume_only": True})])
    result = await drain(maker, ids, assets, "fixed", 5)
    save(
        "access-crash-result",
        {
            "passed": True,
            "synthetic_only": True,
            "production_changed": False,
            "original_delivery": delivery.state,
            "first_committed": True,
            "second_rolled_back": True,
            "pending_cycles": await pending(maker),
            **result,
        },
    )


async def main(args):
    assert 100 <= args.blocked <= 3000 and 1 <= args.eligible <= 1000
    engine = create_async_engine(DATABASE)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        if args.mode == "queue":
            await queue(args, maker)
        else:
            await crash(args, maker)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["baseline", "fixed"], required=True)
    parser.add_argument("--blocked", type=int, default=1000)
    parser.add_argument("--eligible", type=int, default=200)
    parser.add_argument(
        "--mode", choices=["queue", "crash-prepare", "crash-finish"], default="queue"
    )
    asyncio.run(main(parser.parse_args()))

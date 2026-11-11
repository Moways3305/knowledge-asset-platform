"""Real isolated reuse consumers, ordinary queue contention and child-loss recovery."""

import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path

import capacity_metrics  # noqa: F401
import httpx
from capacity_common import DATABASE, guard
from capacity_parse_queue import wait_results, worker_metrics
from capacity_probe import client, distribution, login, save
from capacity_reuse import facts, seed
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

guard()

from app.models.audit import AuditEvent  # noqa: E402
from app.models.lifecycle import NotificationRecord  # noqa: E402
from app.models.outbox import DomainEventOutbox  # noqa: E402
from app.worker.celery_app import celery_app  # noqa: E402


async def pending(maker):
    async with maker() as session:
        return await session.scalar(
            text(
                "SELECT count(*) FROM governance_scan_runs WHERE name='reuse' AND completed_at IS NULL"
            )
        )


async def drain(maker, ids, phase):
    for _ in range(900):
        if phase == "baseline" or not await pending(maker):
            break
        await asyncio.sleep(0.2)
    else:
        raise AssertionError("Reuse continuation stalled")
    # No beat in this measurement. Explicit outbox draining begins AFTER marker
    # timing; it verifies effects, not production notification latency.
    await wait_results(
        [
            celery_app.send_task("domain_events.dispatch_pending")
            for _ in range((len(ids) * 3 + 99) // 100)
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
            .select_from(NotificationRecord)
            .join(AuditEvent, NotificationRecord.audit_event_id == AuditEvent.id)
            .where(AuditEvent.target_id.in_(ids))
        )
    result = await facts(maker, ids)
    result["notifications"] = notices
    assert result["unchanged_with_usage"] == len(ids)
    if phase == "fixed":
        assert result["recommendations"] == result["outbox"] == notices == len(ids), result
    return result


async def queue(args, maker):
    # Startup retries are outside the measurement; measured requests never retry.
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
    ids = await seed(maker, args.count, usage_current=True)
    async with maker() as session:
        # Only the guarded synthetic DB. Previous service-only cohorts stay out
        # of the queue comparison, with their durable facts left for inspection.
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
        scans = [celery_app.send_task("reuse.upgrade_scan") for _ in range(2)]
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
        result = await drain(maker, ids, args.phase)
    finally:
        stop.set()
        await task
    save(
        f"reuse-queue-{args.phase}",
        {
            "passed": True,
            "phase": args.phase,
            "synthetic_only": True,
            "production_changed": False,
            "assets": args.count,
            "ordinary_task_group_seconds": marker_seconds,
            "list_requests": len(latencies),
            "list_statuses": statuses,
            "list_latency": distribution(latencies),
            **result,
            "worker_metrics": worker_metrics(start),
        },
    )


async def crash(args, maker):
    control = Path("/capacity/governance-pause")
    ready = Path("/capacity/governance-paused.json")
    record = Path("/capacity/reuse-crash-private.json")
    if args.mode == "crash-prepare":
        assert not await pending(maker)
        ids = await seed(maker, args.count)
        ready.unlink(missing_ok=True)
        control.write_text("reuse")
        delivery = celery_app.send_task("reuse.upgrade_scan")
        record.write_text(json.dumps({"ids": list(map(str, ids)), "task_id": delivery.id}))
        for _ in range(300):
            if ready.exists():
                info = json.loads(ready.read_text())
                assert info["kind"] == "reuse"
                save("reuse-crash-ready", {"ready": True, **info})
                return
            await asyncio.sleep(0.1)
        control.unlink(missing_ok=True)
        raise AssertionError("Consumer did not pause in reuse batch")
    assert not control.exists(), "Kill the paused isolated child and remove the fault first"
    saved = json.loads(record.read_text())
    ids = [uuid.UUID(value) for value in saved["ids"]]
    delivery = celery_app.AsyncResult(saved["task_id"])
    for _ in range(100):
        if delivery.ready():
            break
        await asyncio.sleep(0.1)
    assert delivery.state == "FAILURE", "Must report actual child loss, not success"
    before = await facts(maker, ids)
    assert before == {"recommendations": 0, "outbox": 0, "unchanged_with_usage": 0}, before
    await wait_results([celery_app.send_task("reuse.upgrade_scan", kwargs={"resume_only": True})])
    result = await drain(maker, ids, "fixed")
    save(
        "reuse-crash-result",
        {
            "passed": True,
            "synthetic_only": True,
            "production_changed": False,
            "original_delivery": delivery.state,
            "assets": len(ids),
            "partial_effects_rolled_back": True,
            "pending_cycles": await pending(maker),
            **result,
        },
    )


async def main(args):
    assert 1 <= args.count <= 5000
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
    parser.add_argument("--count", type=int, default=500)
    parser.add_argument(
        "--mode", choices=["queue", "crash-prepare", "crash-finish"], default="queue"
    )
    asyncio.run(main(parser.parse_args()))

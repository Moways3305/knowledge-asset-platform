"""Isolated parse/default queue contention and restart fixture, synthetic data only.

Use the same total worker CPU/memory budget for baseline and fixed runs. Reports
stay in /capacity. Restart commands prepare a checkpoint for the host to stop only
the disposable parse worker; they never control Docker or contact production.
"""

import argparse
import asyncio
import json
import time
import uuid
from collections import Counter, defaultdict
from types import SimpleNamespace

import httpx
from capacity_common import FIXTURE, guard
from capacity_parse_reconcile import seed, state
from capacity_probe import ROOT, distribution, save
from capacity_project_qa import load

guard()

from app.db.session import get_engine  # noqa: E402
from app.worker.celery_app import celery_app  # noqa: E402
from app.worker.tasks.ops_health import worker_heartbeat  # noqa: E402
from app.worker.tasks.parse import reconcile_parse  # noqa: E402


async def wait_results(deliveries, timeout=100):
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        if all(d.ready() for d in deliveries):
            assert all(d.successful() for d in deliveries), "Synthetic task failed"
            return round(time.monotonic() - started, 3)
        await asyncio.sleep(0.1)
    raise RuntimeError("Isolated queue tasks exceeded the observation deadline")


async def wait_inflight(client, slots):
    for _ in range(150):
        control = (await client.get(FIXTURE + "/control")).json()
        if control["inflight"].get("parse", 0) == slots:
            return
        await asyncio.sleep(0.1)
    raise RuntimeError("Parse consumers did not enter the controlled slow requests")


def worker_metrics(since):
    rows = defaultdict(list)
    for path in ROOT.glob("worker-metrics-*.jsonl"):
        for line in path.read_text().splitlines():
            row = json.loads(line)
            if row["started_at"] >= since:
                rows[f"{row['task']}@{row['queue']}"].append(row)
    return {
        key: {
            "completed": len(items),
            "states": dict(Counter(row["state"] for row in items)),
            "queue": distribution(
                [row["queue_seconds"] for row in items if row["queue_seconds"] is not None]
            ),
            "runtime": distribution([row["runtime_seconds"] for row in items]),
        }
        for key, items in rows.items()
    }


async def mixed(args):
    ids, docs = await seed("budget")
    started_at = time.time()
    async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
        (await client.post(FIXTURE + "/seed", json={"docs": docs, "kbs": []})).raise_for_status()
        deliveries = [reconcile_parse.delay() for _ in range(2)]
        await wait_inflight(client, args.parse_slots)
        tick = time.monotonic()
        marker = worker_heartbeat.delay()
        marker_wait = asyncio.create_task(wait_results([marker], timeout=30))
        normal = asyncio.create_task(
            load(
                SimpleNamespace(
                    label=args.label,
                    concurrency=4,
                    search_concurrency=4,
                    seconds=20,
                    delay=0.8,
                    drain_uploads=True,
                    allow_busy=False,
                )
            )
        )
        await wait_results(deliveries)
        marker_seconds = await marker_wait
        if args.parse_slots == 1:
            assert marker_seconds < 5, "Parse backlog starved the ordinary worker"
        else:
            assert marker_seconds > 10, "Baseline did not reproduce the shared queue blockage"
        slow_seconds = round(time.monotonic() - tick, 3)
        before = await state(ids)
        assert before["active_leases"] == 0
        for doc in docs:
            doc["synthetic_delay"] = 0
        (await client.post(FIXTURE + "/seed", json={"docs": docs, "kbs": []})).raise_for_status()
        await wait_results([reconcile_parse.delay()])
        after = await state(ids)
        assert after["indexed"] == len(ids) and after["failures"] == after["active_leases"] == 0
        await normal
        save(
            "parse-queue-" + args.label,
            {
                "passed": True,
                "parse_slots": args.parse_slots,
                "slow_round_seconds": slow_seconds,
                "marker_seconds": marker_seconds,
                "before_recovery": before,
                "after_recovery": after,
                "worker_metrics": worker_metrics(started_at),
            },
        )


async def prepare_restart(args):
    ids, docs = await seed("concurrent")
    for doc in docs:
        doc["synthetic_delay"] = 3
    async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
        (await client.post(FIXTURE + "/seed", json={"docs": docs, "kbs": []})).raise_for_status()
        deliveries = [reconcile_parse.delay() for _ in range(3)]
        await wait_inflight(client, 1)
    # Only synthetic IDs, for the companion finish command after the host restart.
    save(
        "parse-restart-" + args.label,
        {
            "ids": [str(value) for value in ids],
            "docs": docs,
            "deliveries": [d.id for d in deliveries],
            "started_at": time.time(),
        },
    )


async def finish_restart(args):
    data = json.loads((ROOT / ("parse-restart-" + args.label + ".json")).read_text())
    ids = [uuid.UUID(value) for value in data["ids"]]
    await wait_results([celery_app.AsyncResult(value) for value in data["deliveries"]])
    for doc in data["docs"]:
        doc["synthetic_delay"] = 0
    async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
        (
            await client.post(FIXTURE + "/seed", json={"docs": data["docs"], "kbs": []})
        ).raise_for_status()
        # Hard-lost processes retain their DB lease for at most 120 seconds.
        # Exercise the same periodic scan Beat sends, without shortening the lease.
        until = time.monotonic() + 135
        while time.monotonic() < until:
            await wait_results([reconcile_parse.delay()])
            result = await state(ids)
            if result["indexed"] == len(ids) and result["active_leases"] == 0:
                break
            await asyncio.sleep(2)
        else:
            raise RuntimeError("Synthetic leases did not recover after worker restart")
        first = result
        control = (await client.get(FIXTURE + "/control")).json()
        counts = {doc["id"]: control["parse_calls"].get(doc["id"], 0) for doc in data["docs"]}
        await wait_results([reconcile_parse.delay()])
        result = await state(ids)
        repeated = (await client.get(FIXTURE + "/control")).json()
        assert counts == {
            doc["id"]: repeated["parse_calls"].get(doc["id"], 0) for doc in data["docs"]
        }
        assert result["indexed"] == first["indexed"] and result["failures"] == 0
        save(
            "parse-restart-result-" + args.label,
            {
                "passed": True,
                "state": result,
                "terminal_documents_not_repolled": True,
                "seconds_since_checkpoint": round(time.time() - data["started_at"], 3),
                "worker_metrics": worker_metrics(data["started_at"]),
            },
        )


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["mixed", "prepare-restart", "finish-restart"])
    parser.add_argument("--label", required=True)
    parser.add_argument("--parse-slots", type=int, choices=[1, 2], default=1)
    args = parser.parse_args()
    assert args.label.replace("-", "").isalnum(), "Use a plain synthetic report label"
    try:
        await {
            "mixed": mixed,
            "prepare-restart": prepare_restart,
            "finish-restart": finish_restart,
        }[args.command](args)
    finally:
        await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())

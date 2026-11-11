"""Synthetic notification contention, legacy routing and consumer recovery probes.

Only run inside compose.capacity-test.yml. The host controls disposable workers;
this tool never controls Docker. Reports stay in /capacity, outside the repository.
"""

import argparse
import asyncio
import json
import os
import time
import uuid
from types import SimpleNamespace

import httpx
from capacity_common import FIXTURE, guard
from capacity_parse_queue import wait_results, worker_metrics
from capacity_probe import ROOT, save
from capacity_project_qa import load
from sqlalchemy import delete, select

guard()
if any(
    os.environ.get(key) != value
    for key, value in {
        "WECOM_NOTIFY_ENABLED": "true",
        "WECOM_CORP_ID": "synthetic-only",
        "WECOM_AGENT_ID": "1",
        "WECOM_APP_SECRET": "synthetic-only",
        "WECOM_API_BASE_URL": FIXTURE,
        "WECOM_TIMEOUT": "8",
    }.items()
):
    raise SystemExit("Refusing non-synthetic notification provider")

from app.db.session import get_sessionmaker  # noqa: E402
from app.models.audit import AuditEvent  # noqa: E402
from app.models.identity import User  # noqa: E402
from app.models.ingest import IngestTask  # noqa: E402
from app.models.lifecycle import NotificationRecord  # noqa: E402
from app.models.notification import BusinessNotification  # noqa: E402
from app.worker.celery_app import celery_app  # noqa: E402
from app.worker.tasks.notifications import dispatch_pending  # noqa: E402
from app.worker.tasks.ops_health import worker_heartbeat  # noqa: E402


async def seed(label, count=2):
    prefix = f"notification-queue-{label}-{uuid.uuid4().hex[:8]}"
    ids = []
    async with get_sessionmaker()() as session:
        user = await session.scalar(select(User).where(User.email == "capacity-99@example.invalid"))
        assert user is not None
        user.wecom_user_id = "synthetic-notification-recipient"
        for i in range(count):
            ops = NotificationRecord(
                id=uuid.uuid4(),
                recipient_user_id=user.id,
                channel="wecom",
                title=f"{prefix}-ops-{i}",
                content="Synthetic safe summary",
            )
            session.add(ops)
            ids.append(ops.id)
            task = IngestTask(
                id=uuid.uuid4(),
                source="path_b_upload",
                status="failed",
                created_by=user.id,
                source_file_ref="synthetic",
                source_file_name="synthetic.txt",
                error_type="synthetic_notice_only",
            )
            session.add(task)
            await session.flush()
            notice = BusinessNotification(
                id=uuid.uuid4(),
                recipient_user_id=user.id,
                channel="wecom",
                title=f"{prefix}-business-{i}",
                summary="Synthetic safe summary",
                event_type="ingest.failed",
                category="ingest",
                target_kind="ingest_task",
                target_id=task.id,
                dedup_key=uuid.uuid4().hex,
            )
            session.add(notice)
            ids.append(notice.id)
        await session.commit()
    return ids, prefix


async def state(ids):
    result = {"sent": 0, "failed": 0, "pending": 0, "leases": 0, "attempts": [], "audits": 0}
    async with get_sessionmaker()() as session:
        for model, status, attempts in (
            (NotificationRecord, "send_status", "send_attempts"),
            (BusinessNotification, "delivery_status", "delivery_attempts"),
        ):
            for row in await session.scalars(select(model).where(model.id.in_(ids))):
                result[getattr(row, status)] += 1
                result["attempts"].append(getattr(row, attempts))
                result["leases"] += bool(row.delivery_token)
        result["audits"] = len(
            list(await session.scalars(select(AuditEvent.id).where(AuditEvent.target_id.in_(ids))))
        )
    return result


async def inflight(client, slots):
    for _ in range(200):
        value = (await client.get(FIXTURE + "/control")).json()
        if value["inflight"].get("notification", 0) >= slots:
            return
        await asyncio.sleep(0.1)
    raise RuntimeError("Notification workers did not enter the controlled requests")


async def mixed(args):
    if args.clean_start:
        # Match each comparison's initial pending set. Earlier upload exercises
        # create synthetic notifications too; do not let those bias later runs.
        async with get_sessionmaker()() as session:
            emails = list(await session.scalars(select(User.email)))
            assert len(emails) == 100 and all(e.endswith("@example.invalid") for e in emails)
            for model in (BusinessNotification, NotificationRecord):
                assert (
                    await session.scalar(
                        select(model.id).where(model.delivery_token.is_not(None)).limit(1)
                    )
                    is None
                )
                await session.execute(delete(model))
            await session.commit()
    ids, prefix = await seed(args.label) if not args.normal else ([], "unused")
    started = time.time()
    async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
        (
            await client.post(FIXTURE + "/control", json={"notification_delay": args.delay})
        ).raise_for_status()
        deliveries = [] if args.normal else [dispatch_pending.delay() for _ in range(2)]
        if deliveries:
            await inflight(client, args.slots)
        marker = worker_heartbeat.delay()
        heartbeat_wait = asyncio.create_task(wait_results([marker], timeout=100))
        recoveries = [
            celery_app.send_task(name)
            for name in (
                "ingest.recover_orphans",
                "indexing.recover_interrupted_jobs",
                "domain_events.dispatch_pending",
            )
        ]
        recovery_wait = asyncio.create_task(wait_results(recoveries, timeout=100))
        traffic = asyncio.create_task(
            load(
                SimpleNamespace(
                    label=args.label,
                    concurrency=4,
                    search_concurrency=4,
                    seconds=20,
                    delay=0.8,
                    drain_uploads=True,
                    allow_busy=args.allow_search_busy,
                )
            )
        )
        await wait_results(deliveries, timeout=150)
        marker_seconds, recovery_seconds = await asyncio.gather(heartbeat_wait, recovery_wait)
        await traffic
        before = await state(ids)
        observed = (await client.get(FIXTURE + "/control")).json()
        calls = {k: v for k, v in observed["notification_calls"].items() if k.startswith(prefix)}
        if args.delay < 8 and ids:
            assert before["sent"] == len(ids) and before["leases"] == 0
            assert len(calls) == len(ids) and set(calls.values()) == {1}
            assert before["audits"] == len(ids)
        if args.delay > 8:
            assert before["failed"] == len(ids) and before["leases"] == 0
            assert before["attempts"] == [1] * len(ids)
            # Overlapping scans must not bypass the durable retry schedule.
            await wait_results([dispatch_pending.delay()])
            assert (await state(ids))["attempts"] == before["attempts"]
        (await client.post(FIXTURE + "/control", json={"notification_delay": 0})).raise_for_status()
        save(
            "notification-queue-" + args.label,
            {
                "passed": True,
                "synthetic_only": True,
                "clean_start": args.clean_start,
                "allow_search_busy": args.allow_search_busy,
                "marker_seconds": marker_seconds,
                "recovery_seconds": recovery_seconds,
                "notification_state": before,
                "notification_calls": calls,
                "ids": [str(i) for i in ids],
                "prefix": prefix,
                "worker_metrics": worker_metrics(started),
            },
        )


async def retry(args):
    data = json.loads((ROOT / ("notification-queue-" + args.label + ".json")).read_text())
    ids = [uuid.UUID(i) for i in data["ids"]]
    # Preserve the real 120-second retry delay; host may already have waited part of it.
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        await wait_results([dispatch_pending.delay()])
        result = await state(ids)
        if result["sent"] == len(ids):
            assert result["leases"] == 0 and result["attempts"] == [2] * len(ids)
            save("notification-retry-" + args.label, {"passed": True, "state": result})
            return
        await asyncio.sleep(2)
    raise RuntimeError("Synthetic retry did not converge")


async def prepare(args):
    ids, prefix = await seed(args.label)
    async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
        await client.post(FIXTURE + "/control", json={"notification_delay": 4})
        first = dispatch_pending.delay()
        await inflight(client, 1)
        deliveries = [first, dispatch_pending.delay(), dispatch_pending.delay()]
    save(
        "notification-restart-" + args.label,
        {
            "ids": [str(i) for i in ids],
            "prefix": prefix,
            "deliveries": [d.id for d in deliveries],
            "started_at": time.time(),
        },
    )


async def finish(args):
    data = json.loads((ROOT / ("notification-restart-" + args.label + ".json")).read_text())
    ids = [uuid.UUID(i) for i in data["ids"]]
    async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
        await client.post(FIXTURE + "/control", json={"notification_delay": 0})
    marker = worker_heartbeat.delay()
    marker_seconds = await wait_results([marker])
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        await wait_results([dispatch_pending.delay()])
        result = await state(ids)
        if result["sent"] == len(ids):
            assert result["leases"] == 0 and result["audits"] == len(ids)
            if not args.lost:
                await wait_results([celery_app.AsyncResult(i) for i in data["deliveries"]])
                assert result["attempts"] == [1] * len(ids)
            save(
                "notification-restart-result-" + args.label,
                {
                    "passed": True,
                    "state": result,
                    "lost_worker": args.lost,
                    "original_delivery_states": [
                        celery_app.AsyncResult(i).state for i in data["deliveries"]
                    ],
                    "marker_seconds": marker_seconds,
                    "elapsed": round(time.time() - data["started_at"], 3),
                },
            )
            return
        await asyncio.sleep(2)
    raise RuntimeError("Synthetic notification restart did not converge")


async def legacy(args):
    ids, _ = await seed(args.label, count=1)
    # New code must still execute deliveries published explicitly to the old queue.
    await wait_results([dispatch_pending.apply_async(queue="default")])
    result = await state(ids)
    assert result["sent"] == 2 and result["audits"] == 2 and result["leases"] == 0
    save("notification-legacy-" + args.label, {"passed": True, "state": result})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["mixed", "retry", "prepare", "finish", "legacy"])
    parser.add_argument("--label", required=True)
    parser.add_argument("--slots", type=int, default=1)
    parser.add_argument("--delay", type=float, default=6)
    parser.add_argument("--normal", action="store_true")
    parser.add_argument("--clean-start", action="store_true")
    parser.add_argument("--allow-search-busy", action="store_true")
    parser.add_argument("--lost", action="store_true")
    args = parser.parse_args()
    asyncio.run(globals()[args.command](args))

"""Guarded real-queue notification projection and ordinary-traffic rehearsal."""

import argparse
import asyncio
import json
import time
import uuid
from datetime import timedelta
from pathlib import Path

import capacity_metrics  # noqa: F401
from capacity_common import DATABASE, guard
from capacity_parse_queue import wait_results, worker_metrics
from capacity_probe import client, distribution, login, save
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

guard()

from app.db.utils import utc_now  # noqa: E402
from app.models.identity import User, UserCompanyRole  # noqa: E402
from app.models.knowledge import KnowledgeAsset  # noqa: E402
from app.models.notification import BusinessNotification  # noqa: E402
from app.models.original_access import OriginalAccessRequest  # noqa: E402
from app.models.outbox import DomainEventOutbox  # noqa: E402
from app.services import domain_events  # noqa: E402
from app.worker.celery_app import celery_app  # noqa: E402


async def seed(maker, count=20):
    async with maker() as session:
        existing = await session.scalar(
            select(User.id).where(User.email == "outbox-0@example.invalid")
        )
        if existing is None:
            users = [
                User(
                    id=uuid.uuid4(),
                    name=f"Synthetic {i}",
                    email=f"outbox-{i}@example.invalid",
                    status="active",
                )
                for i in range(1000)
            ]
            session.add_all(users)
            await session.flush()
            session.add_all(
                UserCompanyRole(user_id=u.id, company_role="boss", status="active") for u in users
            )
            await session.commit()
        requester = await session.scalar(
            select(User.id).where(User.email == "capacity-0@example.invalid")
        )
        assets = list(
            await session.scalars(
                select(KnowledgeAsset.id)
                .where(
                    KnowledgeAsset.scope == "company",
                    KnowledgeAsset.id.not_in(select(OriginalAccessRequest.asset_id)),
                )
                .order_by(KnowledgeAsset.id)
                .limit(count)
            )
        )
        assert len(assets) == count
        ids = []
        for asset in assets:
            req = OriginalAccessRequest(
                id=uuid.uuid4(), asset_id=asset, requester_user_id=requester, status="pending"
            )
            session.add(req)
            await session.flush()
            await domain_events.publish(
                session,
                domain_events.DomainEvent(
                    event_type=domain_events.ORIGINAL_ACCESS_REQUESTED,
                    aggregate_type="original_access_request",
                    aggregate_id=req.id,
                    payload={},
                    idempotency_key=f"capacity-outbox:{req.id}",
                ),
            )
            ids.append(req.id)
        await session.commit()
        recipients = await session.scalar(
            select(func.count(func.distinct(UserCompanyRole.user_id)))
            .join(User, User.id == UserCompanyRole.user_id)
            .where(
                User.status == "active",
                UserCompanyRole.status == "active",
                UserCompanyRole.company_role.in_(("boss", "consulting_director")),
            )
        )
        return ids, recipients


async def facts(maker, ids):
    async with maker() as session:
        notices = await session.scalar(
            select(func.count())
            .select_from(BusinessNotification)
            .where(BusinessNotification.target_id.in_(ids))
        )
        completed = await session.scalar(
            select(func.count())
            .select_from(DomainEventOutbox)
            .where(DomainEventOutbox.aggregate_id.in_(ids), DomainEventOutbox.status == "completed")
        )
        pending_requests = await session.scalar(
            select(func.count())
            .select_from(OriginalAccessRequest)
            .where(OriginalAccessRequest.id.in_(ids), OriginalAccessRequest.status == "pending")
        )
        return {
            "notices": notices,
            "completed_events": completed,
            "requests_unchanged": pending_requests,
        }


async def main(phase):
    engine = create_async_engine(DATABASE)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        if phase.startswith("crash-"):
            await crash(maker, phase)
            return
        for _ in range(30):
            if await asyncio.to_thread(celery_app.control.ping, timeout=1):
                break
            await asyncio.sleep(0.2)
        else:
            raise AssertionError("Isolated worker not ready")
        ids, recipients = await seed(maker)
        start = time.time()
        stop = asyncio.Event()
        latencies, statuses = [], {}

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
                    statuses[str(response.status_code)] = (
                        statuses.get(str(response.status_code), 0) + 1
                    )
                    assert response.status_code == 200
                    await asyncio.sleep(0.05)

        browsing = asyncio.create_task(traffic())
        try:
            dispatchers = [celery_app.send_task("domain_events.dispatch_pending") for _ in range(2)]
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
            await wait_results(dispatchers, timeout=180)
            marker_seconds = await marker_wait
            for _ in range(900):
                current = await facts(maker, ids)
                if current["completed_events"] == len(ids):
                    break
                await asyncio.sleep(0.2)
            assert current == {
                "notices": len(ids) * recipients,
                "completed_events": len(ids),
                "requests_unchanged": len(ids),
            }, current
        finally:
            stop.set()
            await browsing
        save(
            f"outbox-queue-{phase}",
            {
                "passed": True,
                "synthetic_only": True,
                "production_changed": False,
                "events": len(ids),
                "recipients_per_event": recipients,
                "ordinary_task_group_seconds": marker_seconds,
                "list_requests": len(latencies),
                "list_statuses": statuses,
                "list_latency": distribution(latencies),
                **current,
                "worker_metrics": worker_metrics(start),
                "transaction_and_connection_metrics": transaction_metrics(start),
            },
        )
    finally:
        await engine.dispose()


def transaction_metrics(start):
    rows = [
        json.loads(line)
        for path in Path("/capacity").glob("outbox-transactions-*.jsonl")
        for line in path.read_text().splitlines()
    ]
    return {
        kind: {
            "count": len(values),
            "max_ms": round(max(values, default=0) * 1000, 1),
            **distribution(values),
        }
        for kind in ("transaction", "connection")
        if (
            values := [
                r["seconds"]
                for r in rows
                if r["kind"] == kind
                and r["at"] >= start
                and r.get("task") == "domain_events.dispatch_pending"
            ]
        )
    }


async def crash(maker, mode):
    control = Path("/capacity/outbox-pause")
    ready = Path("/capacity/outbox-paused.json")
    record = Path("/capacity/outbox-crash-private.json")
    if mode == "crash-prepare":
        ids, recipients = await seed(maker, count=1)
        async with maker() as session:
            event_id = await session.scalar(
                select(DomainEventOutbox.id).where(DomainEventOutbox.aggregate_id == ids[0])
            )
        ready.unlink(missing_ok=True)
        control.write_text(str(event_id))
        task = celery_app.send_task("domain_events.dispatch_pending")
        record.write_text(
            json.dumps(
                {
                    "target": str(ids[0]),
                    "event_id": str(event_id),
                    "task_id": task.id,
                    "recipients": recipients,
                }
            )
        )
        for _ in range(300):
            if ready.exists():
                current = await facts(maker, ids)
                assert current["notices"] == 50 and current["completed_events"] == 0, current
                save(
                    "outbox-crash-ready",
                    {
                        **json.loads(ready.read_text()),
                        "first_page_committed": True,
                        "second_page_uncommitted": True,
                    },
                )
                return
            await asyncio.sleep(0.1)
        raise AssertionError("Second page did not reach the fault boundary")
    assert not control.exists(), "Kill the isolated child and remove its fault first"
    saved = json.loads(record.read_text())
    ids = [uuid.UUID(saved["target"])]
    task = celery_app.AsyncResult(saved["task_id"])
    for _ in range(100):
        if task.ready():
            break
        await asyncio.sleep(0.1)
    assert task.state == "FAILURE", task.state
    current = await facts(maker, ids)
    assert current["notices"] == 50 and current["completed_events"] == 0, current
    async with maker() as session:
        row = await session.get(DomainEventOutbox, uuid.UUID(saved["event_id"]))
        assert row.status == "processing" and row.recipient_cursor and row.claim_token
        # Accelerate only this synthetic claim's lease after verifying the crash.
        row.claimed_at = utc_now() - timedelta(seconds=301)
        await session.commit()
    await wait_results([celery_app.send_task("domain_events.dispatch_pending")], timeout=180)
    for _ in range(900):
        current = await facts(maker, ids)
        if current["completed_events"] == 1:
            break
        await asyncio.sleep(0.2)
    assert current == {
        "notices": saved["recipients"],
        "completed_events": 1,
        "requests_unchanged": 1,
    }, current
    save(
        "outbox-crash-result",
        {
            "passed": True,
            "synthetic_only": True,
            "production_changed": False,
            "original_delivery": task.state,
            "first_page_preserved": True,
            "second_page_rolled_back": True,
            **current,
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["baseline", "fixed", "crash-prepare", "crash-finish"])
    asyncio.run(main(parser.parse_args().phase))

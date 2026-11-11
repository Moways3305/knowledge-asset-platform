"""Synthetic governance scan measurements; only the disposable capacity database.

Run each phase with the same runtime/resources. No provider calls or production data.
The service benchmark suppresses only outbox wakeups; events remain durable and are
checked. Queue contention is measured separately with real Celery consumers.
"""

import argparse
import asyncio
import json
import resource
import time
import uuid
from datetime import timedelta
from pathlib import Path

from capacity_common import DATABASE, guard
from sqlalchemy import event, func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

guard()

from app.db.utils import utc_now  # noqa: E402
from app.models.identity import User  # noqa: E402
from app.models.knowledge import KnowledgeAsset  # noqa: E402
from app.models.lifecycle import AssetLifecycleEvent  # noqa: E402
from app.models.outbox import DomainEventOutbox  # noqa: E402
from app.services import knowledge_review  # noqa: E402
from app.services.jobs import lifecycle_scan  # noqa: E402

PREFIX = "capacity-lifecycle-"


async def no_wakeup(_session):
    pass


async def seed(maker, count):
    async with maker() as session:
        user = await session.scalar(select(User).where(User.email == "capacity-99@example.invalid"))
        assert user is not None
        await session.execute(
            update(KnowledgeAsset)
            .where(KnowledgeAsset.title.startswith(PREFIX))
            .values(asset_status="archived")
        )
        now = utc_now()
        rows = [
            KnowledgeAsset(
                id=uuid.uuid4(),
                title=f"{PREFIX}{count}-{i}",
                scope="personal",
                zone="asset",
                asset_type="document",
                owner_user_id=user.id,
                maintainer_user_id=user.id,
                visibility="private",
                confidentiality_level="L1",
                ai_access_level="A1",
                asset_status="active",
                created_at=now - timedelta(days=800),
                review_due_at=now - timedelta(days=1),
            )
            for i in range(count)
        ]
        session.add_all(rows)
        await session.commit()
        return [row.id for row in rows]


async def measure(maker, engine, phase, kind):
    statements = 0
    users = 0
    transactions = []
    beginnings = {}

    def sql(_conn, _cursor, statement, _parameters, _context, _many):
        nonlocal statements, users
        statements += 1
        if "FROM users" in statement:
            users += 1

    def begin(conn):
        beginnings[id(conn)] = time.monotonic()

    def end(conn):
        started = beginnings.pop(id(conn), None)
        if started is not None:
            transactions.append(time.monotonic() - started)

    listeners = [
        ("before_cursor_execute", sql),
        ("begin", begin),
        ("commit", end),
        ("rollback", end),
    ]
    for name, fn in listeners:
        event.listen(engine.sync_engine, name, fn)
    started = time.monotonic()
    calls = 0
    try:
        while True:
            async with maker() as session:
                kwargs = {"resume_only": calls > 0} if phase == "fixed" else {}
                if kind == "archive":
                    await lifecycle_scan.scan_archive_candidates(session, **kwargs)
                else:
                    await knowledge_review.scan_due_reviews(session, **kwargs)
            calls += 1
            if phase == "baseline":
                break
            async with maker() as session:
                pending = await session.scalar(
                    text(
                        "SELECT completed_at IS NULL FROM governance_scan_runs WHERE name = :name"
                    ),
                    {"name": kind},
                )
            if not pending:
                break
            assert calls < 500, "Scan did not finish"
        elapsed = time.monotonic() - started
    finally:
        for name, fn in listeners:
            event.remove(engine.sync_engine, name, fn)
    return {
        "seconds": round(elapsed, 3),
        "statements": statements,
        "user_loads": users,
        "transactions": len(transactions),
        "max_transaction_seconds": round(max(transactions, default=0), 4),
        "calls": calls,
        "process_peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2),
    }


async def main(args):
    assert 1 <= args.count <= 5000 and all(1 <= n <= 5000 for n in args.counts)
    if args.mode.startswith("crash-"):
        await crash_probe(args)
        return
    if args.mode == "queue":
        await queue_probe(args)
        return
    lifecycle_scan.enqueue_outbox_delivery = no_wakeup
    knowledge_review.enqueue_outbox_delivery = no_wakeup
    engine = create_async_engine(
        DATABASE, connect_args={"server_settings": {"application_name": "kap-lifecycle-probe"}}
    )
    maker = async_sessionmaker(engine, expire_on_commit=False)
    results = []
    try:
        for count in args.counts:
            ids = await seed(maker, count)
            measurements = {}
            for kind in ("archive", "review"):
                measurements[kind] = await measure(maker, engine, args.phase, kind)
            async with maker() as session:
                warnings = await session.scalar(
                    select(func.count())
                    .select_from(AssetLifecycleEvent)
                    .where(AssetLifecycleEvent.asset_id.in_(ids))
                )
                events = await session.scalar(
                    select(func.count())
                    .select_from(DomainEventOutbox)
                    .where(DomainEventOutbox.aggregate_id.in_(ids))
                )
                unchanged = await session.scalar(
                    select(func.count())
                    .select_from(KnowledgeAsset)
                    .where(KnowledgeAsset.id.in_(ids), KnowledgeAsset.asset_status == "active")
                )
            assert warnings == count and events == count * 2 and unchanged == count, (
                warnings,
                events,
                unchanged,
            )
            result = {
                "assets": count,
                "phase": args.phase,
                **measurements,
                "warning_count": warnings,
                "outbox_count": events,
                "business_state_unchanged": True,
            }
            results.append(result)
            print(json.dumps(result), flush=True)
        with open(f"/capacity/lifecycle-{args.phase}.json", "w") as out:
            json.dump(
                {"synthetic_only": True, "production_changed": False, "results": results},
                out,
                indent=2,
            )
    finally:
        await engine.dispose()


async def queue_probe(args):
    import capacity_metrics  # noqa: F401
    from capacity_parse_queue import wait_results, worker_metrics
    from capacity_probe import client, distribution, login, save

    from app.models.audit import AuditEvent
    from app.models.lifecycle import NotificationRecord
    from app.models.notification import BusinessNotification
    from app.worker.celery_app import celery_app

    engine = create_async_engine(DATABASE)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    ids = await seed(maker, args.count)
    # Prior service-only measurements left durable outbox rows. Exclude those
    # from both queue comparisons; never execute against a non-synthetic DB.
    async with maker() as session:
        emails = list(await session.scalars(select(User.email)))
        assert len(emails) == 100 and all(value.endswith("@example.invalid") for value in emails)
        await session.execute(update(DomainEventOutbox).values(status="completed"))
        await session.commit()
    started = time.time()
    latencies = []
    statuses = {}
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
                assert response.status_code == 200 and isinstance(
                    response.json().get("items"), list
                )
                await asyncio.sleep(0.05)

    traffic_task = asyncio.create_task(traffic())
    try:
        scans = [celery_app.send_task("lifecycle.archive_scan") for _ in range(2)]
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
        # Beat is deliberately absent in this controlled queue comparison. Its
        # normal 15-second outbox wakeups are replaced AFTER timing the ordinary
        # jobs, so checking all notification effects cannot bias that timing.
        drains = [
            celery_app.send_task("domain_events.dispatch_pending")
            for _ in range((args.count * 3 + 99) // 100)
        ]
        await wait_results(drains, timeout=180)
        for _ in range(900):
            async with maker() as session:
                pending_cycle = args.phase == "fixed" and await session.scalar(
                    text("SELECT count(*) FROM governance_scan_runs WHERE completed_at IS NULL")
                )
                pending_events = await session.scalar(
                    select(func.count())
                    .select_from(DomainEventOutbox)
                    .where(
                        DomainEventOutbox.aggregate_id.in_(ids),
                        DomainEventOutbox.status != "completed",
                    )
                )
            if not pending_cycle and not pending_events:
                break
            await asyncio.sleep(0.2)
        else:
            raise AssertionError("Synthetic scans or outbox did not drain")
        async with maker() as session:
            warnings = await session.scalar(
                select(func.count())
                .select_from(AssetLifecycleEvent)
                .where(AssetLifecycleEvent.asset_id.in_(ids))
            )
            audits = await session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.target_id.in_(ids), AuditEvent.action == "lifecycle.archive_warning"
                )
            )
            reviews = await session.scalar(
                select(func.count())
                .select_from(BusinessNotification)
                .where(BusinessNotification.target_id.in_(ids))
            )
            notices = await session.scalar(
                select(func.count())
                .select_from(NotificationRecord)
                .join(AuditEvent, NotificationRecord.audit_event_id == AuditEvent.id)
                .where(AuditEvent.target_id.in_(ids))
            )
            active = await session.scalar(
                select(func.count())
                .select_from(KnowledgeAsset)
                .where(KnowledgeAsset.id.in_(ids), KnowledgeAsset.asset_status == "active")
            )
        assert active == args.count
        if args.phase == "fixed":
            assert warnings == audits == reviews == notices == args.count, (
                warnings,
                audits,
                reviews,
                notices,
            )
    finally:
        stop.set()
        await traffic_task
        await engine.dispose()
    save(
        f"lifecycle-queue-{args.phase}",
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
            "warnings": warnings,
            "warning_audits": audits,
            "review_notifications": reviews,
            "archive_notifications": notices,
            "worker_metrics": worker_metrics(started),
        },
    )


async def crash_probe(args):
    from capacity_parse_queue import wait_results
    from capacity_probe import save

    from app.worker.celery_app import celery_app

    engine = create_async_engine(DATABASE)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    control = Path("/capacity/governance-pause")
    ready = Path("/capacity/governance-paused.json")
    record = Path(f"/capacity/governance-crash-{args.fault_kind}.json")
    try:
        if args.mode == "crash-prepare":
            ids = await seed(maker, args.count)
            async with maker() as session:
                assert not await session.scalar(
                    text("SELECT count(*) FROM governance_scan_runs WHERE completed_at IS NULL")
                )
                business = [
                    (str(row.id), str(row.updated_at), row.asset_status)
                    for row in await session.scalars(
                        select(KnowledgeAsset)
                        .where(KnowledgeAsset.id.in_(ids))
                        .order_by(KnowledgeAsset.id)
                    )
                ]
            ready.unlink(missing_ok=True)
            control.write_text(args.fault_kind)
            delivery = celery_app.send_task("lifecycle.archive_scan")
            record.write_text(
                json.dumps(
                    {"ids": list(map(str, ids)), "task_id": delivery.id, "business": business}
                )
            )
            for _ in range(300):
                if ready.exists():
                    info = json.loads(ready.read_text())
                    assert info["kind"] == args.fault_kind
                    save(f"governance-crash-prepared-{args.fault_kind}", {"ready": True, **info})
                    return
                await asyncio.sleep(0.1)
            control.unlink(missing_ok=True)
            raise AssertionError("Fault consumer did not pause inside the expected batch")
        assert not control.exists(), "Host must kill the paused child and remove the fault first"
        saved = json.loads(record.read_text())
        ids = [uuid.UUID(value) for value in saved["ids"]]
        original = celery_app.AsyncResult(saved["task_id"])
        for _ in range(100):
            if original.ready():
                break
            await asyncio.sleep(0.1)
        assert original.state == "FAILURE", (
            "Original task must record worker loss, not fake success"
        )
        await wait_results(
            [celery_app.send_task("lifecycle.archive_scan", kwargs={"resume_only": True})]
        )
        for _ in range(300):
            async with maker() as session:
                pending = await session.scalar(
                    text("SELECT count(*) FROM governance_scan_runs WHERE completed_at IS NULL")
                )
            if not pending:
                break
            await asyncio.sleep(0.1)
        else:
            raise AssertionError("Pending cycle failed to resume after child loss")
        await wait_results(
            [
                celery_app.send_task("domain_events.dispatch_pending")
                for _ in range((len(ids) * 2 + 99) // 100)
            ]
        )
        async with maker() as session:
            business = [
                (str(row.id), str(row.updated_at), row.asset_status)
                for row in await session.scalars(
                    select(KnowledgeAsset)
                    .where(KnowledgeAsset.id.in_(ids))
                    .order_by(KnowledgeAsset.id)
                )
            ]
            assert [list(row) for row in business] == saved["business"]
            warnings = await session.scalar(
                select(func.count())
                .select_from(AssetLifecycleEvent)
                .where(AssetLifecycleEvent.asset_id.in_(ids))
            )
            rows = list(
                await session.scalars(
                    select(DomainEventOutbox).where(DomainEventOutbox.aggregate_id.in_(ids))
                )
            )
            assert (
                warnings == len(ids)
                and len(rows) == len(ids) * 2
                and all(row.status == "completed" for row in rows)
            )
        save(
            f"governance-crash-result-{args.fault_kind}",
            {
                "passed": True,
                "synthetic_only": True,
                "production_changed": False,
                "interrupted_kind": args.fault_kind,
                "original_delivery": original.state,
                "assets": len(ids),
                "warnings": warnings,
                "completed_outbox_events": len(rows),
                "business_state_and_timestamps_unchanged": True,
                "pending_cycles": 0,
            },
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["baseline", "fixed"], required=True)
    parser.add_argument(
        "--mode", choices=["service", "queue", "crash-prepare", "crash-finish"], default="service"
    )
    parser.add_argument("--count", type=int, default=500)
    parser.add_argument("--fault-kind", choices=["archive", "review"], default="archive")
    parser.add_argument("--counts", nargs="+", type=int, default=[100, 500, 1500])
    asyncio.run(main(parser.parse_args()))

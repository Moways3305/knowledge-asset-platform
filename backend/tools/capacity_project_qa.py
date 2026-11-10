"""Disposable QA + login/list/upload contention probe, never a production load tool.

Use after capacity_probe.py seed in compose.capacity-test.yml. Run `seed` once,
then `load --label before --concurrency 8 --seconds 20` on each source revision.
Reports include all HTTP outcomes, response validity and database transaction
samples. Synthetic HTTP providers measure application contention, not model speed.
Pass --drain-uploads with real isolated workers to verify generation, confirmation,
indexing, one audit per file and the content-generation usage delta as well.
"""

import argparse
import asyncio
import json
import time
import uuid
from collections import Counter, defaultdict

import httpx
from capacity_common import FIXTURE, PASSWORD, email, guard
from capacity_probe import ROOT, client, distribution, drain, login, save
from sqlalchemy import select, text

guard()
import capacity_metrics  # noqa: E402, F401

from app.db.session import get_engine, get_sessionmaker  # noqa: E402
from app.models.identity import Project, ProjectMember, User  # noqa: E402
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion  # noqa: E402
from app.models.weknora import WeknoraKbMapping  # noqa: E402
from app.schemas.enums import AuditAction  # noqa: E402


async def seed():
    project_id, kb = uuid.uuid4(), "capacity-project-qa"
    docs = []
    async with get_sessionmaker()() as session:
        assert await session.scalar(select(Project.id)) is None, "Use a fresh disposable project"
        users = list(await session.scalars(select(User)))
        assert len(users) == 100 and all(u.email.endswith("@example.invalid") for u in users)
        session.add(Project(id=project_id, name="Synthetic capacity QA project"))
        await session.flush()
        session.add_all(
            ProjectMember(user_id=u.id, project_id=project_id, project_role="consultant")
            for u in users
        )
        session.add(
            WeknoraKbMapping(scope="project", project_id=project_id, weknora_kb_id=kb, kb_name=kb)
        )
        for i in range(10):
            asset_id, version_id, doc_id = uuid.uuid4(), uuid.uuid4(), f"capacity-qa-{i}"
            session.add(
                KnowledgeAsset(
                    id=asset_id,
                    title=f"Synthetic QA material {i}",
                    scope="project",
                    project_id=project_id,
                    zone="material",
                    asset_type="document",
                    owner_user_id=users[0].id,
                    current_version_id=version_id,
                    visibility="project",
                    confidentiality_level="L2",
                    ai_access_level="A1",
                )
            )
            session.add(
                KnowledgeAssetVersion(
                    id=version_id,
                    asset_id=asset_id,
                    version_no="V1",
                    version_status="active",
                    created_by=users[0].id,
                    index_status="indexed",
                    weknora_kb_id=kb,
                    weknora_doc_id=doc_id,
                    weknora_parse_status="completed",
                )
            )
            docs.append({"id": doc_id, "knowledge_base_id": kb, "parse_status": "completed"})
        await session.commit()
    async with httpx.AsyncClient(trust_env=False) as c:
        response = await c.post(FIXTURE + "/seed", json={"docs": docs, "kbs": [{"id": kb}]})
        response.raise_for_status()
    save("qa-seed", {"project_id": str(project_id), "assets": 10, "synthetic_only": True})


async def load(args):
    project_id = json.loads((ROOT / "qa-seed.json").read_text())["project_id"]
    assert 1 <= args.concurrency <= 64 and 1 <= args.seconds <= 120
    search_workers = getattr(args, "search_concurrency", 0)
    heavy_workers = args.concurrency + search_workers
    assert 0 <= search_workers and heavy_workers <= 64
    clients = [client() for _ in range(heavy_workers + 3)]
    stop, samples = asyncio.Event(), []
    timings, statuses, errors = defaultdict(list), defaultdict(Counter), Counter()
    status_timings = defaultdict(lambda: defaultdict(list))
    denials = Counter()
    uploads = []
    sampler = None

    def metrics_snapshot():
        return {p.name: json.loads(p.read_text()) for p in ROOT.glob("api-metrics-*.json")}

    metrics_before = metrics_snapshot()
    wall_started = time.time()
    async with get_sessionmaker()() as session:
        usage_before = dict(
            (
                await session.execute(
                    text(
                        "SELECT outcome,count(*) FROM llm_usage_events "
                        "WHERE scenario='content_generation' GROUP BY outcome"
                    )
                )
            ).all()
        )
    async with httpx.AsyncClient(trust_env=False) as control:
        response = await control.post(
            FIXTURE + "/control", json={"llm_delay": args.delay, "search_delay": args.delay}
        )
        response.raise_for_status()
        fixture_before = response.json()

    async def sample():
        while not stop.is_set():
            async with get_sessionmaker()() as session:
                rows = (
                    await session.execute(
                        text(
                            "SELECT state, count(*) FROM pg_stat_activity "
                            "WHERE datname=current_database() "
                            "AND application_name='kap-capacity-api' GROUP BY state"
                        )
                    )
                ).all()
                activity = (
                    (
                        await session.execute(
                            text(
                                "SELECT pid, state, wait_event_type, wait_event, "
                                "extract(epoch from clock_timestamp()-xact_start) AS xact_age, "
                                "extract(epoch from clock_timestamp()-state_change) AS state_age, "
                                "(regexp_match(query, '(FROM|UPDATE|INTO) ([a-z_]+)'))[2] "
                                "AS relation FROM pg_stat_activity "
                                "WHERE datname=current_database() "
                                "AND application_name='kap-capacity-api' AND state<>'idle'"
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                worker_rows = (
                    (
                        await session.execute(
                            text(
                                "SELECT state, count(*) AS connections, "
                                "count(*) FILTER (WHERE EXISTS (SELECT 1 FROM pg_locks l "
                                "WHERE l.pid=a.pid AND l.locktype='advisory' AND l.granted)) "
                                "AS lock_owners, "
                                "max(extract(epoch from clock_timestamp()-xact_start)) AS age "
                                "FROM pg_stat_activity a WHERE datname=current_database() "
                                "AND application_name='kap-capacity-worker' GROUP BY state"
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
            samples.append(
                {
                    "elapsed": round(time.monotonic() - started, 3),
                    "states": dict(rows),
                    "api_activity": [
                        {
                            **row,
                            "xact_age": float(row["xact_age"] or 0),
                            "state_age": float(row["state_age"] or 0),
                        }
                        for row in activity
                    ],
                    "worker_states": [
                        {**row, "age": float(row["age"]) if row["age"] is not None else None}
                        for row in worker_rows
                    ],
                }
            )
            try:
                await asyncio.wait_for(stop.wait(), 0.1)
            except asyncio.TimeoutError:
                pass

    async def operation(c, kind, index):
        tick = time.monotonic()
        response = None
        try:
            if kind == "qa":
                response = await c.post(
                    f"/api/v1/projects/{project_id}/qa",
                    json={"query": "Synthetic capacity benchmark question"},
                )
            elif kind == "search":
                response = await c.post(
                    "/api/v1/knowledge/search",
                    json={
                        "query": "Synthetic capacity benchmark question",
                        "intent": "search",
                        "scope": "project",
                        "filters": {"project_id": project_id},
                    },
                )
            elif kind == "list":
                response = await c.get(
                    "/api/v1/knowledge",
                    params={
                        "scope": "company",
                        "directory_key": "company.introduction",
                        "page_size": 20,
                    },
                )
            elif kind == "login":
                response = await c.post(
                    "/api/v1/auth/login", json={"email": email(index), "password": PASSWORD}
                )
            else:
                label = f"capacity-qa-{uuid.uuid4().hex}"
                response = await c.post(
                    "/api/v1/ingest/upload",
                    data={"target_scope": "personal", "formed_on": "2026-11-09"},
                    files={
                        "file": (label + ".txt", (label + " Synthetic material. " * 30).encode())
                    },
                )
            statuses[kind][str(response.status_code)] += 1
            if response.is_success:
                body = response.json()
                if kind == "qa" and (
                    body.get("answer_status") != "answered" or not body.get("citations")
                ):
                    errors["invalid_qa_answer"] += 1
                elif kind == "list" and len(body.get("items", [])) != 20:
                    errors["incorrect_page"] += 1
                elif kind == "search" and not body.get("cards"):
                    errors["invalid_search_cards"] += 1
                elif kind == "upload":
                    uploads.append(body["ingest_task_id"])
            else:
                errors[kind + "_http_" + str(response.status_code)] += 1
                try:
                    reason = response.json().get("detail", {}).get("denied_reason")
                except (ValueError, AttributeError):
                    reason = None
                known = {
                    "search_busy",
                    "search_timeout",
                    "external_llm_unavailable",
                    "qa_context_changed",
                }
                denials[reason if reason in known else "unclassified"] += 1
        except httpx.HTTPError as exc:
            statuses[kind][type(exc).__name__] += 1
            errors[kind + "_" + type(exc).__name__] += 1
        finally:
            elapsed = time.monotonic() - tick
            timings[kind].append(elapsed)
            status_timings[kind][
                str(response.status_code) if response is not None else "transport_error"
            ].append(elapsed)

    async def worker(c, kind, index):
        while time.monotonic() - started < args.seconds:
            await operation(c, kind, index)
            # Bound login attempts/upload volume; QA remains closed-loop.
            if kind not in {"qa", "search"}:
                await asyncio.sleep(0.5 if kind == "list" else 1)

    try:
        for _ in range(30):
            try:
                ready = await clients[0].get("/api/v1/knowledge")
                if ready.status_code == 401:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1)
        else:
            raise RuntimeError("Isolated API did not become ready")
        for i, c in enumerate(clients):
            await login(c, i)
        started = time.monotonic()
        sampler = asyncio.create_task(sample())
        await asyncio.gather(
            *(
                worker(
                    c,
                    "qa"
                    if i < args.concurrency
                    else "search"
                    if i < heavy_workers
                    else ("list", "login", "upload")[i - heavy_workers],
                    i,
                )
                for i, c in enumerate(clients)
            )
        )
        elapsed = time.monotonic() - started
        processing = None
        if args.drain_uploads:
            # Same authenticated uploader; keep sampling the real workers through
            # generation, user confirmation and asynchronous indexing completion.
            await drain(clients[-1], uploads, started)
            processing = json.loads((ROOT / "uploads.json").read_text())
            async with get_sessionmaker()() as session:
                audits = await session.execute(
                    text(
                        "SELECT target_id, count(*) FROM audit_events "
                        "WHERE action=:action "
                        "AND target_id=ANY(CAST(:ids AS uuid[])) GROUP BY target_id"
                    ),
                    {"ids": uploads, "action": AuditAction.ingest_ai_extracted.value},
                )
                counts = [row[1] for row in audits]
                usage_after = dict(
                    (
                        await session.execute(
                            text(
                                "SELECT outcome,count(*) FROM llm_usage_events "
                                "WHERE scenario='content_generation' GROUP BY outcome"
                            )
                        )
                    ).all()
                )
            processing["usage_delta"] = {
                key: value - usage_before.get(key, 0)
                for key, value in usage_after.items()
                if value != usage_before.get(key, 0)
            }
            processing["one_generation_audit_per_upload"] = len(counts) == len(uploads) and all(
                n == 1 for n in counts
            )
            assert processing["one_generation_audit_per_upload"]
            assert processing["usage_delta"] == {"success": len(uploads)}
        stop.set()
        await sampler
        # Continue observing the ordinary endpoint after QA load has drained.
        for _ in range(3):
            await operation(clients[0], "list", 0)
        async with httpx.AsyncClient(trust_env=False) as control:
            fixture_after = (await control.get(FIXTURE + "/control")).json()
        if processing is not None:
            processing["model_calls"] = fixture_after["counts"].get("content", 0) - fixture_before[
                "counts"
            ].get("content", 0)
            assert processing["model_calls"] == len(uploads)
        await asyncio.sleep(0.2)  # Wait for process-local metric snapshots to flush.
        measurements = defaultdict(list)
        metrics_truncated = False
        metrics_after = metrics_snapshot()
        for name, snapshot in metrics_after.items():
            before = metrics_before.get(name, {}).get("counts", {})
            for key, values in snapshot["metrics"].items():
                count = snapshot["counts"].get(key, 0) - before.get(key, 0)
                metrics_truncated |= count > len(values)
                if count > 0:
                    measurements[key].extend(v / 1000 for v in values[-count:])
        worker_metrics = defaultdict(list)
        for path in ROOT.glob("worker-metrics-*.jsonl"):
            for line in path.read_text().splitlines():
                row = json.loads(line)
                if row["started_at"] >= wall_started:
                    worker_metrics[f"{row['task']}@{row['queue']}"].append(row)
        report = {
            "label": args.label,
            "qa_concurrency": args.concurrency,
            "search_concurrency": search_workers,
            "light_workers": 3,
            "requested_seconds": args.seconds,
            "elapsed_seconds": round(elapsed, 2),
            "provider_delay_seconds": args.delay,
            "synthetic_only": True,
            "errors": errors,
            "denials": denials,
            "operations": {
                k: {
                    "requests": len(v),
                    "statuses": statuses[k],
                    **distribution(v),
                    "latency_by_status": {
                        code: distribution(items) for code, items in status_timings[k].items()
                    },
                }
                for k, v in timings.items()
            },
            "idle_in_transaction_peak": max(
                s["states"].get("idle in transaction", 0) for s in samples
            ),
            "idle_in_transaction_samples": sum(
                s["states"].get("idle in transaction", 0) > 0 for s in samples
            ),
            "samples": samples,
            "fixture_before": fixture_before,
            "fixture_after": fixture_after,
            "upload_task_ids": uploads,
            "upload_acceptance_only": not args.drain_uploads,
            "upload_processing": processing,
            "api_metrics": {
                k: {"count": len(v), **distribution(v), "max_ms": round(max(v) * 1000, 3)}
                for k, v in measurements.items()
                if v
            },
            "api_metrics_truncated": metrics_truncated,
            "worker_metrics": {
                key: {
                    "completed": len(rows),
                    "states": Counter(r["state"] for r in rows),
                    "queue": distribution(
                        [r["queue_seconds"] for r in rows if r["queue_seconds"] is not None]
                    ),
                    "runtime": distribution([r["runtime_seconds"] for r in rows]),
                }
                for key, rows in worker_metrics.items()
            },
            "idle_transaction_max_age_seconds": max(
                (
                    r["xact_age"]
                    for s in samples
                    for r in s["api_activity"]
                    if r["state"] == "idle in transaction"
                ),
                default=0,
            ),
        }
        save(f"qa-load-{args.label}", report)
        if getattr(args, "allow_busy", False):
            assert set(errors) <= {"qa_http_503", "search_http_503"}, dict(errors)
            assert sum(errors.values()) == denials.get("search_busy", 0), dict(denials)
        else:
            assert not errors, dict(errors)
    finally:
        stop.set()
        if sampler:
            await sampler
        await asyncio.gather(*(c.aclose() for c in clients))


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed")
    p = sub.add_parser("load")
    p.add_argument("--label", required=True)
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--search-concurrency", type=int, default=0)
    p.add_argument("--seconds", type=int, default=20)
    p.add_argument("--delay", type=float, default=0.8)
    p.add_argument("--drain-uploads", action="store_true")
    p.add_argument("--allow-busy", action="store_true", help="Only permit guarded search_busy 503s")
    args = parser.parse_args()
    try:
        await (seed() if args.command == "seed" else load(args))
    finally:
        await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())

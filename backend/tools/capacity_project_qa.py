"""Disposable QA + login/list/upload contention probe, never a production load tool.

Use after capacity_probe.py seed in compose.capacity-test.yml. Run `seed` once,
then `load --label before --concurrency 8 --seconds 20` on each source revision.
Reports include all HTTP outcomes, response validity and database transaction
samples. Synthetic HTTP providers measure application contention, not model speed.
"""

import argparse
import asyncio
import json
import time
import uuid
from collections import Counter, defaultdict

import httpx
from capacity_common import FIXTURE, PASSWORD, email, guard
from capacity_probe import ROOT, client, distribution, login, save
from sqlalchemy import select, text

guard()
from app.db.session import get_engine, get_sessionmaker  # noqa: E402
from app.models.identity import Project, ProjectMember, User  # noqa: E402
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion  # noqa: E402
from app.models.weknora import WeknoraKbMapping  # noqa: E402


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
    clients = [client() for _ in range(args.concurrency + 3)]
    stop, samples = asyncio.Event(), []
    timings, statuses, errors = defaultdict(list), defaultdict(Counter), Counter()
    uploads = []
    sampler = None
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
            samples.append({"elapsed": round(time.monotonic() - started, 3), "states": dict(rows)})
            try:
                await asyncio.wait_for(stop.wait(), 0.1)
            except asyncio.TimeoutError:
                pass

    async def operation(c, kind, index):
        tick = time.monotonic()
        try:
            if kind == "qa":
                response = await c.post(
                    f"/api/v1/projects/{project_id}/qa",
                    json={"query": "Synthetic capacity benchmark question"},
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
                elif kind == "upload":
                    uploads.append(body["ingest_task_id"])
            else:
                errors[kind + "_http_" + str(response.status_code)] += 1
        except httpx.HTTPError as exc:
            statuses[kind][type(exc).__name__] += 1
            errors[kind + "_" + type(exc).__name__] += 1
        finally:
            timings[kind].append(time.monotonic() - tick)

    async def worker(c, kind, index):
        while time.monotonic() - started < args.seconds:
            await operation(c, kind, index)
            # Bound login attempts/upload volume; QA remains closed-loop.
            if kind != "qa":
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
                    else ("list", "login", "upload")[i - args.concurrency],
                    i,
                )
                for i, c in enumerate(clients)
            )
        )
        elapsed = time.monotonic() - started
        stop.set()
        await sampler
        # Continue observing the ordinary endpoint after QA load has drained.
        for _ in range(3):
            await operation(clients[0], "list", 0)
        async with httpx.AsyncClient(trust_env=False) as control:
            fixture_after = (await control.get(FIXTURE + "/control")).json()
        report = {
            "label": args.label,
            "qa_concurrency": args.concurrency,
            "light_workers": 3,
            "requested_seconds": args.seconds,
            "elapsed_seconds": round(elapsed, 2),
            "provider_delay_seconds": args.delay,
            "synthetic_only": True,
            "errors": errors,
            "operations": {
                k: {"requests": len(v), "statuses": statuses[k], **distribution(v)}
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
            "upload_acceptance_only": True,
        }
        save(f"qa-load-{args.label}", report)
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
    p.add_argument("--seconds", type=int, default=20)
    p.add_argument("--delay", type=float, default=0.8)
    args = parser.parse_args()
    try:
        await (seed() if args.command == "seed" else load(args))
    finally:
        await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())

"""Run only with deploy/compose.capacity-test.yml; all data is disposable.

Examples (inside the probe container):
  python /probe/capacity_probe.py smoke
  python /probe/capacity_probe.py load --kind mixed --concurrency 16 --seconds 30
  python /probe/capacity_probe.py uploads --count 20
Reports go to /capacity, not the repository. Concurrency means in-flight requests,
not human users. Closed-loop tests do not measure overload admission or true model
capacity. The fixture's delays are reported with every run.
"""

import argparse
import asyncio
import importlib.metadata
import io
import json
import math
import re
import subprocess
import time
import uuid
from collections import Counter
from pathlib import Path

import httpx
from capacity_common import API, FIXTURE, PASSWORD, email, guard
from redis.asyncio import Redis
from sqlalchemy import func, select, text

guard()
from app.db.session import get_engine, get_sessionmaker  # noqa: E402
from app.models.identity import User, UserCompanyRole  # noqa: E402
from app.models.ingest import IngestTask  # noqa: E402
from app.models.knowledge import (  # noqa: E402
    KnowledgeAsset,
    KnowledgeAssetSummary,
    KnowledgeAssetVersion,
)

ROOT = Path("/capacity")
USERS = 100
ASSETS = 3000


def client():
    # Trust only the disposable certificate generated in this same isolated volume.
    import ssl

    return httpx.AsyncClient(
        base_url=API,
        verify=ssl.create_default_context(cafile=str(ROOT / "cert.pem")),
        timeout=35,
        trust_env=False,
    )


def save(name, value):
    (ROOT / f"{name}.json").write_text(json.dumps(value, indent=2), encoding="utf-8")
    print(json.dumps(value), flush=True)


async def seed():
    from packaging.requirements import Requirement

    from app.models.naming import NamingRuleRevision
    from app.models.weknora import WeknoraKbMapping
    from app.models.weknora_defaults import WeknoraDefaultModels
    from app.services.directories import default_directory_config
    from app.services.passwords import hash_password

    # A cached image is acceptable only if every locked distribution is installed.
    for line in Path("/locked-requirements.txt").read_text().splitlines():
        if not re.match(r"^[A-Za-z0-9_-]+==", line):
            continue
        requirement = Requirement(line.rstrip(" \\"))
        if requirement.marker and not requirement.marker.evaluate():
            continue
        assert importlib.metadata.version(requirement.name) in requirement.specifier, (
            requirement.name
        )
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    ROOT.mkdir(exist_ok=True)
    if not (ROOT / "cert.pem").exists():
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "2",
                "-subj",
                "/CN=api",
                "-addext",
                "subjectAltName=DNS:api",
                "-keyout",
                str(ROOT / "key.pem"),
                "-out",
                str(ROOT / "cert.pem"),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    docs, kbs = [], []
    async with get_sessionmaker()() as session:
        if await session.scalar(select(func.count()).select_from(User)):
            # Do not silently reseed a database with existing mutable test state.
            raise RuntimeError("Capacity database is not empty; use a fresh project/volume")
        digest = hash_password(PASSWORD)
        users = [
            User(
                id=uuid.uuid4(),
                email=email(i),
                name=f"Synthetic user {i}",
                password_hash=digest,
                company_roles=[UserCompanyRole(company_role="consultant")],
            )
            for i in range(USERS)
        ]
        session.add_all(users)
        await session.flush()
        revision = await session.scalar(
            select(NamingRuleRevision).where(NamingRuleRevision.status == "published")
        )
        if revision is None:
            revision = NamingRuleRevision(version=1, base_published_version=0, status="published")
            session.add(revision)
        revision.config = {
            "schema_version": 2,
            "enforced": True,
            "project_codes": [],
            "categories": [],
            "directories": default_directory_config(),
        }
        session.add(
            WeknoraDefaultModels(
                default_embedding_model_id="capacity-embedding",
                default_chat_model_id="capacity-chat",
            )
        )
        for index, user in enumerate(users):
            kb_id = f"capacity-personal-{index}"
            session.add(
                WeknoraKbMapping(
                    scope="personal",
                    owner_user_id=user.id,
                    weknora_kb_id=kb_id,
                    embedding_model_id="capacity-embedding",
                    kb_name=kb_id,
                    display_name="Synthetic personal library",
                )
            )
            kbs.append(
                {
                    "id": kb_id,
                    "name": kb_id,
                    "embedding_model_id": "capacity-embedding",
                    "summary_model_id": "capacity-chat",
                    "llmModelId": "capacity-chat",
                    "embeddingModelId": "capacity-embedding",
                }
            )
        kb_id = "capacity-company"
        session.add(
            WeknoraKbMapping(
                scope="company",
                weknora_kb_id=kb_id,
                embedding_model_id="capacity-embedding",
                kb_name=kb_id,
            )
        )
        kbs.append({"id": kb_id, "name": kb_id})
        for index in range(ASSETS):
            asset_id, version_id = uuid.uuid4(), uuid.uuid4()
            owner = users[index % USERS]
            personal = index % 3 == 0
            kb = f"capacity-personal-{index % USERS}" if personal else kb_id
            doc_id = f"capacity-doc-{index}"
            session.add(
                KnowledgeAsset(
                    id=asset_id,
                    title=f"Capacity synthetic benchmark {index:05}",
                    scope="personal" if personal else "company",
                    zone="material",
                    asset_type="document",
                    owner_user_id=owner.id,
                    current_version_id=version_id,
                    visibility="public",
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
                    created_by=owner.id,
                    index_status="indexed",
                    weknora_kb_id=kb,
                    weknora_doc_id=doc_id,
                    weknora_parse_status="completed",
                    directory_key="personal.learning_notes" if personal else "company.introduction",
                )
            )
            session.add(
                KnowledgeAssetSummary(
                    asset_id=asset_id,
                    version_id=version_id,
                    summary_type="one_liner",
                    content="Synthetic capacity material",
                )
            )
            docs.append({"id": doc_id, "knowledge_base_id": kb, "parse_status": "completed"})
        await session.commit()
    async with httpx.AsyncClient(trust_env=False) as c:
        response = await c.post(FIXTURE + "/seed", json={"docs": docs, "kbs": kbs})
        response.raise_for_status()
    save(
        "seed",
        {
            "users": USERS,
            "assets": ASSETS,
            "migrations": "head",
            "locked_dependencies_verified": True,
            "synthetic_only": True,
        },
    )


async def login(c, index):
    response = await c.post(
        "/api/v1/auth/login", json={"email": email(index), "password": PASSWORD}
    )
    response.raise_for_status()
    assert c.cookies.get("kap_session"), "No password session cookie"
    response = await c.get("/api/v1/auth/csrf")
    response.raise_for_status()
    c.headers["X-CSRF-Token"] = response.json()["csrf_token"]


async def smoke():
    async with client() as c:
        assert (await c.get("/api/v1/knowledge")).status_code == 401
        await login(c, 0)
        response = await c.get(
            "/api/v1/knowledge",
            params={"scope": "company", "directory_key": "company.introduction", "page_size": 20},
        )
        assert response.status_code == 200, response.text
        assert len(response.json()["items"]) == 20
        response = await c.post(
            "/api/v1/knowledge/search",
            json={"query": "Capacity synthetic benchmark", "intent": "search", "scope": "company"},
        )
        response.raise_for_status()
        assert response.json()["cards"], response.json()
        c.headers.pop("X-CSRF-Token")
        assert (
            await c.post("/api/v1/knowledge/search", json={"query": "Capacity"})
        ).status_code == 403
    save(
        "smoke",
        {
            "passed": True,
            "password_session": True,
            "tls": True,
            "unauthenticated_denied": True,
            "csrf_enforced": True,
            "search_cards_returned": True,
        },
    )


async def sample(stop, rows):
    redis = Redis.from_url("redis://redis:6379/0")
    try:
        while not stop.is_set():
            async with get_sessionmaker()() as session:
                counts = dict(
                    (
                        await session.execute(
                            text(
                                "SELECT state, count(*) FROM pg_stat_activity WHERE datname=current_database() GROUP BY state"
                            )
                        )
                    ).all()
                )
                tasks = dict(
                    (
                        await session.execute(
                            select(IngestTask.status, func.count()).group_by(IngestTask.status)
                        )
                    ).all()
                )
            rows.append(
                {
                    "time": time.time(),
                    "db_connections": counts,
                    "ingest": tasks,
                    "queues": {q: await redis.llen(q) for q in ("default", "ocr")},
                }
            )
            try:
                await asyncio.wait_for(stop.wait(), 1)
            except asyncio.TimeoutError:
                pass
    finally:
        await redis.aclose()


def distribution(values):
    ordered = sorted(values)
    return {
        f"p{percentile}_ms": round(
            ordered[max(0, math.ceil(len(ordered) * percentile / 100) - 1)] * 1000, 1
        )
        if ordered
        else None
        for percentile in (50, 95, 99)
    }


async def load(args):
    async with client() as c:
        for _attempt in range(30):
            try:
                response = await c.get("/api/v1/knowledge")
                if response.status_code == 401:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1)
        else:
            raise RuntimeError("Isolated API did not become ready")
    if args.login_history:
        import socket

        from app.services.auth_security import hash_login_identifier

        # Simulate a busy office/NAT before issuing any HTTP login requests.
        ip_hash = hash_login_identifier(socket.gethostbyname(socket.gethostname()), purpose="ip")
        async with get_sessionmaker()() as session:
            await session.execute(
                text("DELETE FROM auth_login_attempts WHERE identifier_hash = repeat('c', 64)")
            )
            await session.execute(
                text(
                    "INSERT INTO auth_login_attempts (id, identifier_hash, ip_hash, login_method, result, created_at) SELECT gen_random_uuid(), repeat('c', 64), :ip, 'password', 'success', now() - interval '1 minute' FROM generate_series(1, :history)"
                ),
                {"ip": ip_hash, "history": args.login_history},
            )
            await session.commit()
    clients = [client() for _ in range(args.concurrency)]
    try:
        for start in range(0, len(clients), 5):
            await asyncio.gather(
                *(login(c, i % USERS) for i, c in enumerate(clients[start : start + 5], start))
            )
        latency, errors, kinds, samples = [], Counter(), Counter(), []
        per_kind = {key: [] for key in ("list", "login", "search")}
        stop = asyncio.Event()
        sampler = asyncio.create_task(sample(stop, samples))
        started = time.monotonic()

        async def worker(c, index):
            number = 0
            while time.monotonic() - started < args.seconds:
                kind = args.kind
                if kind == "mixed":
                    kind = ("list", "list", "search", "search", "login")[(number + index) % 5]
                tick = time.monotonic()
                try:
                    if kind == "login":
                        response = await c.post(
                            "/api/v1/auth/login",
                            json={"email": email(index % USERS), "password": PASSWORD},
                        )
                    elif kind == "search":
                        response = await c.post(
                            "/api/v1/knowledge/search",
                            json={
                                "query": "Capacity synthetic benchmark",
                                "scope": "company",
                                "intent": "search",
                            },
                        )
                    else:
                        response = await c.get(
                            "/api/v1/knowledge",
                            params={
                                "scope": "company",
                                "directory_key": "company.introduction",
                                "page_size": 20,
                                "page": 1 + number % 5,
                            },
                        )
                    if response.status_code != 200:
                        errors[f"http_{response.status_code}"] += 1
                    elif kind == "search" and not response.json().get("cards"):
                        errors["empty_search"] += 1
                    elif kind == "list" and len(response.json().get("items", [])) != 20:
                        errors["incorrect_page"] += 1
                    kinds[kind] += 1
                except httpx.HTTPError as exc:
                    errors[type(exc).__name__] += 1
                duration = time.monotonic() - tick
                latency.append(duration)
                per_kind[kind].append(duration)
                # Login rotates the cookie, so renew its CSRF binding outside the measured operation.
                if kind == "login":
                    csrf = await c.get("/api/v1/auth/csrf")
                    csrf.raise_for_status()
                    c.headers["X-CSRF-Token"] = csrf.json()["csrf_token"]
                number += 1

        try:
            await asyncio.gather(*(worker(c, i) for i, c in enumerate(clients)))
        finally:
            stop.set()
            await sampler
        elapsed = time.monotonic() - started
        async with httpx.AsyncClient(trust_env=False) as c:
            fixture = (await c.get(FIXTURE + "/control")).json()
        report = {
            "synthetic_login_history": args.login_history,
            "kind": args.kind,
            "concurrency": args.concurrency,
            "requested_seconds": args.seconds,
            "elapsed_seconds": round(elapsed, 2),
            "requests": len(latency),
            "rps": round(len(latency) / elapsed, 2),
            "errors": errors,
            "operations": kinds,
            "per_operation": {
                key: distribution(values) for key, values in per_kind.items() if values
            },
            **distribution(latency),
            "samples": samples,
            "fixture": fixture,
        }
        save(f"load-{args.label}-{args.kind}-{args.concurrency}", report)
    finally:
        await asyncio.gather(*(c.aclose() for c in clients))


async def uploads(args):
    from docx import Document

    started = time.monotonic()
    tasks = []
    async with client() as c:
        await login(c, 0)
        for i in range(args.count):
            label = f"capacity-{uuid.uuid4().hex}"
            if i % 2:
                document = Document()
                document.add_paragraph(f"{label}. Synthetic capacity material. " * 30)
                stream = io.BytesIO()
                document.save(stream)
                content, ext = stream.getvalue(), "docx"
            else:
                content, ext = (f"{label}. Synthetic capacity material. " * 30).encode(), "txt"
            response = await c.post(
                "/api/v1/ingest/upload",
                data={"target_scope": "personal", "formed_on": "2026-11-09"},
                files={"file": (f"{label}.{ext}", content)},
            )
            response.raise_for_status()
            tasks.append(response.json()["ingest_task_id"])
        (ROOT / "latest-tasks.json").write_text(json.dumps(tasks))
        if args.submit_only:
            save(
                "submitted",
                {"tasks": len(tasks), "elapsed_seconds": round(time.monotonic() - started, 2)},
            )
            return
        await drain(c, tasks, started)


async def drain(c, tasks, started):
    pending = set(tasks)
    results = []
    while pending and time.monotonic() - started < 240:
        for key in list(pending):
            response = await c.get(f"/api/v1/ingest/{key}/status")
            response.raise_for_status()
            data = response.json()
            if data["stage"] == "awaiting_confirmation":
                response = await c.post(
                    f"/api/v1/ingest/{key}/confirm",
                    json={
                        "title": f"Capacity {key[:8]}",
                        "summary": "Synthetic capacity material",
                        "tags": [],
                        "target_scope": "personal",
                        "target_zone": "material",
                        "confidentiality_level": "L2",
                        "directory_key": "personal.learning_notes",
                    },
                )
                response.raise_for_status()
                assert response.json()["status"] == "completed", response.json()
                results.append(response.json()["result_asset_id"])
                pending.remove(key)
            elif data["stage"] in {"failed", "cancelled"}:
                raise RuntimeError(f"Synthetic task ended in {data['stage']}")
        if pending:
            await asyncio.sleep(1)
    assert not pending, f"{len(pending)} unfinished synthetic tasks"
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        async with get_sessionmaker()() as session:
            versions = (
                await session.execute(
                    select(
                        KnowledgeAssetVersion.asset_id, KnowledgeAssetVersion.index_status
                    ).where(
                        KnowledgeAssetVersion.asset_id.in_([uuid.UUID(value) for value in results])
                    )
                )
            ).all()
        if len(versions) == len(tasks) and all(status == "indexed" for _, status in versions):
            break
        await asyncio.sleep(1)
    assert len(versions) == len(tasks) and all(status == "indexed" for _, status in versions), (
        Counter(status for _, status in versions)
    )
    async with get_sessionmaker()() as session:
        filenames = (
            await session.scalars(
                select(IngestTask.source_file_name).where(
                    IngestTask.id.in_([uuid.UUID(key) for key in tasks])
                )
            )
        ).all()
    save(
        "uploads",
        {
            "passed": True,
            "submitted": len(tasks),
            "confirmed": len(results),
            "unique_assets": len(set(results)),
            "indexed": len(versions),
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "formats": sorted({Path(name).suffix.lstrip(".") for name in filenames}),
        },
    )


async def guard_benchmark(args):
    """Same security guard and PostgreSQL, with an explicit synthetic NAT history.

    Count materialized ORM records as well as time; this distinguishes algorithmic
    work from host noise. No password hashing is included in this component test.
    """
    from sqlalchemy import event

    from app.models.auth_security import AuthLoginAttempt
    from app.services.auth_security import check_login_guard

    async with get_sessionmaker()() as session:
        await session.execute(
            text("DELETE FROM auth_login_attempts WHERE identifier_hash = repeat('b', 64)")
        )
        await session.execute(
            text(
                "INSERT INTO auth_login_attempts (id, identifier_hash, ip_hash, login_method, result, created_at) SELECT gen_random_uuid(), repeat('b', 64), repeat('a', 64), 'password', 'success', now() - interval '1 minute' FROM generate_series(1, :history)"
            ),
            {"history": args.history},
        )
        await session.commit()
    materialized = 0

    def count_row(target, context):
        nonlocal materialized
        materialized += 1

    event.listen(AuthLoginAttempt, "load", count_row)
    durations = []
    try:
        for _ in range(10):
            async with get_sessionmaker()() as session:
                started = time.monotonic()
                result = await check_login_guard(
                    session, identifier_hash="b" * 64, ip_hash="a" * 64
                )
                durations.append(time.monotonic() - started)
                assert not result.blocked and result.failed_count == 0
    finally:
        event.remove(AuthLoginAttempt, "load", count_row)
    save(
        f"guard-{args.label}-{args.history}",
        {
            "history": args.history,
            "calls": len(durations),
            "materialized_attempt_rows": materialized,
            **distribution(durations),
        },
    )


async def main(args):
    try:
        if args.command == "seed":
            await seed()
        elif args.command == "smoke":
            await smoke()
        elif args.command == "load":
            await load(args)
        elif args.command == "uploads":
            stop = asyncio.Event()
            rows = []
            sampler = asyncio.create_task(sample(stop, rows))
            try:
                await uploads(args)
            finally:
                stop.set()
                await sampler
                save("upload-queues", {"samples": rows})
        elif args.command == "guard-bench":
            await guard_benchmark(args)
        elif args.command == "drain":
            async with client() as c:
                await login(c, 0)
                await drain(
                    c, json.loads((ROOT / "latest-tasks.json").read_text()), time.monotonic()
                )
    finally:
        await get_engine().dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["seed", "smoke", "load", "uploads", "drain", "guard-bench"]
    )
    parser.add_argument("--kind", choices=["login", "list", "search", "mixed"], default="mixed")
    parser.add_argument("--concurrency", type=int, choices=range(1, 129), default=1)
    parser.add_argument("--seconds", type=int, choices=range(5, 121), default=20)
    parser.add_argument("--count", type=int, choices=range(1, 101), default=20)
    parser.add_argument(
        "--label", choices=["baseline", "fixed", "slow", "timeout"], default="baseline"
    )
    parser.add_argument("--submit-only", action="store_true")
    parser.add_argument("--history", type=int, choices=[0, 1000, 20000], default=20000)
    parser.add_argument("--login-history", type=int, choices=[0, 20000], default=0)
    asyncio.run(main(parser.parse_args()))

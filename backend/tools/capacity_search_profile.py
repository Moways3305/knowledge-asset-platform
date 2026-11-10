"""Synthetic-only ASGI CPU/SQL profile; use HTTPS load probes for throughput.

Run in the capacity probe container after seed. Instrumentation stays in this
process, never in the API workers. Reports contain no SQL parameters or bodies.
"""

import argparse
import asyncio
import cProfile
import hashlib
import json
import pstats
import time
from collections import Counter, defaultdict
from pathlib import Path

import httpx
from capacity_common import API, guard

guard()

from capacity_probe import login  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import get_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import search  # noqa: E402


async def run(label, count):
    rows = []
    current = {}
    statements = {}
    engine = get_engine()

    def before(conn, cursor, statement, parameters, context, executemany):
        context.capacity_started = time.perf_counter()

    def after(conn, cursor, statement, parameters, context, executemany):
        if not current:
            return
        fingerprint = hashlib.sha256(statement.encode()).hexdigest()[:12]
        statements[fingerprint] = statement
        bucket = current["sql"][fingerprint]
        bucket["calls"] += 1
        bucket["rows"] += max(cursor.rowcount, 0)
        bucket["ms"] += (time.perf_counter() - context.capacity_started) * 1000

    def loaded(session, instance):
        if current:
            current["orm_loaded"][type(instance).__name__] += 1

    original_enter = search._SearchProgress.enter

    def enter(progress, stage, trace_id):
        if current:
            current["stages_ms"][progress.stage] += (time.monotonic() - progress.entered_at) * 1000
        original_enter(progress, stage, trace_id)

    event.listen(engine.sync_engine, "before_cursor_execute", before)
    event.listen(engine.sync_engine, "after_cursor_execute", after)
    event.listen(Session, "loaded_as_persistent", loaded)
    search._SearchProgress.enter = enter
    profile = cProfile.Profile()
    body = {"query": "Capacity synthetic benchmark", "intent": "search", "scope": "company"}
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=API, trust_env=False
            ) as client,
        ):
            await login(client, 0)
            for index in range(count + 2):
                current = {
                    "sql": defaultdict(lambda: {"calls": 0, "rows": 0, "ms": 0.0}),
                    "orm_loaded": Counter(),
                    "stages_ms": defaultdict(float),
                }
                if index >= 2:
                    profile.enable()
                started = time.perf_counter()
                response = await client.post("/api/v1/knowledge/search", json=body)
                elapsed = (time.perf_counter() - started) * 1000
                profile.disable()
                response.raise_for_status()
                cards = response.json()["cards"]
                assert cards
                current["wall_ms"] = elapsed
                current["card_count"] = len(cards)
                current["cards_sha256"] = hashlib.sha256(
                    json.dumps(cards, sort_keys=True).encode()
                ).hexdigest()
                if index >= 2:
                    rows.append(current)
                current = {}
    finally:
        search._SearchProgress.enter = original_enter
        event.remove(engine.sync_engine, "before_cursor_execute", before)
        event.remove(engine.sync_engine, "after_cursor_execute", after)
        event.remove(Session, "loaded_as_persistent", loaded)
        await engine.dispose()
    stats = pstats.Stats(profile)
    profile.dump_stats(f"/capacity/search-profile-{label}.prof")
    functions = [
        {
            "file": file,
            "line": line,
            "function": name,
            "calls": nc,
            "self_ms": tt * 1000,
            "cumulative_ms": ct * 1000,
        }
        for (file, line, name), (_cc, nc, tt, ct, _callers) in stats.stats.items()
    ]
    report = {
        "scope": "isolated in-process ASGI profile; not a throughput measurement",
        "requests": rows,
        "sql_shapes_without_parameters": statements,
        "top_self": sorted(functions, key=lambda r: -r["self_ms"])[:40],
        "top_cumulative": sorted(functions, key=lambda r: -r["cumulative_ms"])[:50],
    }
    path = Path("/capacity") / f"search-profile-{label}.json"
    path.write_text(json.dumps(report, indent=2))
    print(json.dumps({"report": str(path), "requests": len(rows), "cards": rows[0]["card_count"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", choices=["baseline", "fixed"], required=True)
    parser.add_argument("--count", type=int, choices=range(1, 21), default=5)
    args = parser.parse_args()
    asyncio.run(run(args.label, args.count))

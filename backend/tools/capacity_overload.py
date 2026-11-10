"""Bounded bursts, real HTTPS disconnects and deadlines in the isolated stack only.

Run via the probe service of deploy/compose.capacity-test.yml. Uses synthetic
password sessions and HTTP model fixtures, never production endpoints/credentials.
Reports contain only counts, timings and fixed assertion names, not bodies/tokens.
"""

import asyncio
import time
import uuid
from collections import Counter

import httpx
from capacity_common import FIXTURE, guard
from capacity_probe import client, distribution, login, save
from sqlalchemy import text

guard()
from app.db.session import get_engine, get_sessionmaker  # noqa: E402

SEARCH = "/api/v1/knowledge/search"
BODY = {"query": "Capacity synthetic benchmark", "scope": "company", "intent": "search"}


async def main():
    clients = [client() for _ in range(64)]
    report = {"synthetic_only": True, "real_model_test": False, "checks": []}

    def check(name, passed, **details):
        report["checks"].append({"case": name, "passed": bool(passed), **details})
        if not passed:
            raise RuntimeError(name)

    async def control(**settings):
        async with httpx.AsyncClient(trust_env=False) as c:
            r = await c.post(FIXTURE + "/control", json=settings)
            r.raise_for_status()
            return r.json()

    async def until(predicate, seconds=5):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            state = await control()
            if predicate(state):
                return state
            await asyncio.sleep(0.05)
        raise RuntimeError("fixture_condition_timeout")

    async def light_operations(c):
        measured = {}
        start = time.monotonic()
        await login(c, 99)
        measured["login_ms"] = round((time.monotonic() - start) * 1000, 1)
        start = time.monotonic()
        response = await c.get(
            "/api/v1/knowledge",
            params={"scope": "company", "directory_key": "company.introduction", "page_size": 20},
        )
        check(
            "list_during_saturation",
            response.status_code == 200 and len(response.json().get("items", [])) == 20,
        )
        measured["list_ms"] = round((time.monotonic() - start) * 1000, 1)
        start = time.monotonic()
        response = await c.post(
            "/api/v1/ingest/upload",
            data={"target_scope": "personal", "formed_on": "2026-11-10"},
            files={
                "file": (
                    f"capacity-{uuid.uuid4().hex}.txt",
                    b"Synthetic overload acceptance material.",
                )
            },
        )
        check(
            "upload_during_saturation",
            response.status_code == 200 and bool(response.json().get("ingest_task_id")),
        )
        measured["upload_ms"] = round((time.monotonic() - start) * 1000, 1)
        check("light_operations_responsive", max(measured.values()) < 3000, **measured)

    pending = []
    try:
        for start in range(0, len(clients), 4):
            await asyncio.gather(
                *(login(c, i) for i, c in enumerate(clients[start : start + 4], start))
            )
        await control(llm_delay=1.5, search_delay=1.5)
        before = await control()

        async def request(c):
            start = time.monotonic()
            r = await c.post(SEARCH, json=BODY)
            elapsed = time.monotonic() - start
            if r.status_code == 503:
                assert r.json()["detail"]["denied_reason"] == "search_busy"
                assert r.headers["Retry-After"] == "2"
            elif r.status_code == 200:
                assert r.json().get("cards")
            return r.status_code, elapsed

        pending = [asyncio.create_task(request(c)) for c in clients]
        await until(lambda state: state["inflight"].get("planning", 0) >= 4)
        async with client() as light:
            await light_operations(light)
        results = await asyncio.gather(*pending)
        statuses = Counter(str(status) for status, _ in results)
        rejected = [elapsed for status, elapsed in results if status == 503]
        check(
            "bounded_burst",
            set(statuses) == {"200", "503"} and 0 < statuses["200"] <= 16,
            requests=len(results),
            statuses=statuses,
            rejected_latency=distribution(rejected),
        )
        check("busy_response_without_waiting_for_upstream", max(rejected) < 1.5)
        after = await control()
        check(
            "rejected_requests_do_not_call_model",
            after["counts"].get("planning", 0) - before["counts"].get("planning", 0)
            == statuses["200"],
        )

        # Close real HTTPS requests while each is waiting on the model fixture.
        await control(llm_delay=4, search_delay=0.05)
        for iteration in range(3):
            before = await control()
            pending = [asyncio.create_task(request(c)) for c in clients[:8]]
            await until(
                lambda state, before=before: (
                    state["counts"].get("planning", 0) >= before["counts"].get("planning", 0) + 8
                )
            )
            start = time.monotonic()
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            await until(
                lambda state, before=before: (
                    state["counts"].get("planning_disconnected", 0)
                    >= before["counts"].get("planning_disconnected", 0) + 8
                ),
                seconds=2,
            )
            check(
                "client_disconnect_closes_outbound_socket",
                True,
                round=iteration + 1,
                requests=8,
                cleanup_ms=round((time.monotonic() - start) * 1000, 1),
            )
            await control(llm_delay=0.05)
            recovered = await asyncio.gather(*(request(c) for c in clients[:8]))
            check(
                "capacity_recovers_after_disconnect",
                all(status == 200 for status, _ in recovered),
                round=iteration + 1,
            )
            await control(llm_delay=4)

        # Exercise the production default 30-second processing deadline. Fixture
        # recall takes 45 seconds; its normal WeKnora HTTP timeout would be 30 too,
        # but planning time makes the shared whole-request deadline expire first.
        await control(llm_delay=1, search_delay=45)
        before = await control()
        start = time.monotonic()
        response = await clients[0].post(SEARCH, json=BODY)
        elapsed = time.monotonic() - start
        check(
            "whole_request_deadline",
            response.status_code == 504
            and response.json()["detail"]["denied_reason"] == "search_timeout",
            elapsed_seconds=round(elapsed, 2),
        )
        check("deadline_is_bounded", 29 <= elapsed <= 32)
        await until(
            lambda state: (
                state["counts"].get("search_disconnected", 0)
                > before["counts"].get("search_disconnected", 0)
            ),
            seconds=2,
        )
        check("timeout_closes_outbound_socket", True)
        await control(llm_delay=0.05, search_delay=0.05)
        recovered = await asyncio.gather(*(request(c) for c in clients[:8]))
        check("capacity_recovers_after_timeout", all(status == 200 for status, _ in recovered))
        async with get_sessionmaker()() as db:
            idle_transactions = await db.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND state='idle in transaction'"
                )
            )
        check("no_idle_database_transactions", idle_transactions == 0)
        report["passed"] = True
    except Exception as exc:
        report["passed"] = False
        report["error_type"] = type(exc).__name__
        raise
    finally:
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await control(llm_delay=0.05, search_delay=0.05)
        await asyncio.gather(*(c.aclose() for c in clients))
        await get_engine().dispose()
        save("overload", report)


if __name__ == "__main__":
    asyncio.run(main())

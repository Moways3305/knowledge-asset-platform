"""Real password-login bursts beside authenticated list reads in isolation.

Run after capacity_probe.py seed. Optional KAP_CAPACITY_PASSWORD_DELAY on the
isolated API inserts CPU-worker waiting before the real hash, for a controlled
connection-retention comparison. It is not a real CPU throughput measurement.
"""

import argparse
import asyncio
import time
from collections import Counter

import httpx
from capacity_common import PASSWORD, email, guard
from capacity_probe import client, distribution, login, save
from sqlalchemy import text

guard()
from app.db.session import get_engine, get_sessionmaker  # noqa: E402


async def run(label, bursts):
    assert all(1 <= n <= 96 for n in bursts)
    ordinary = client()
    try:
        for _ in range(40):
            try:
                response = await ordinary.get("/api/v1/auth/csrf")
                response.raise_for_status()
                break
            except httpx.HTTPError:
                await asyncio.sleep(0.5)
        else:
            raise RuntimeError("Isolated API unavailable")
        await login(ordinary, 99)
        for count in bursts:
            clients = [client() for _ in range(count)]
            stop, samples = asyncio.Event(), []
            pending = sampler = None
            try:
                for connection in clients:
                    response = await connection.get("/api/v1/auth/csrf")
                    response.raise_for_status()
                    connection.headers["X-CSRF-Token"] = response.json()["csrf_token"]

                async def sample(stop=stop, samples=samples):
                    while not stop.is_set():
                        async with get_sessionmaker()() as session:
                            rows = (
                                (
                                    await session.execute(
                                        text(
                                            "SELECT state, count(*) AS n, "
                                            "max(extract(epoch from clock_timestamp()-xact_start)) AS age "
                                            "FROM pg_stat_activity WHERE application_name='kap-capacity-api' "
                                            "AND datname=current_database() GROUP BY state"
                                        )
                                    )
                                )
                                .mappings()
                                .all()
                            )
                            samples.append([dict(row, age=float(row["age"] or 0)) for row in rows])
                        await asyncio.sleep(0.03)

                timings, codes = [], []

                async def attempt(connection, index, timings=timings, codes=codes):
                    tick = time.monotonic()
                    result = await connection.post(
                        "/api/v1/auth/login", json={"email": email(index), "password": PASSWORD}
                    )
                    timings.append(time.monotonic() - tick)
                    codes.append(result.status_code)

                sampler = asyncio.create_task(sample())
                pending = asyncio.gather(*(attempt(c, i) for i, c in enumerate(clients)))
                light, light_codes = [], []
                while not pending.done():
                    tick = time.monotonic()
                    response = await ordinary.get(
                        "/api/v1/knowledge",
                        params={
                            "scope": "company",
                            "directory_key": "company.introduction",
                            "page_size": 20,
                        },
                    )
                    light.append(time.monotonic() - tick)
                    light_codes.append(response.status_code)
                    assert response.status_code == 200 and len(response.json()["items"]) == 20
                    await asyncio.sleep(0.03)
                await pending
                stop.set()
                await sampler
                report = {
                    "synthetic_only": True,
                    "label": label,
                    "logins": count,
                    "statuses": Counter(codes),
                    "login_latency": distribution(timings),
                    "list_latency": distribution(light),
                    "list_count": len(light),
                    "list_statuses": Counter(light_codes),
                    "max_idle_seconds": max(
                        (
                            r["age"]
                            for s in samples
                            for r in s
                            if r["state"] == "idle in transaction"
                        ),
                        default=0,
                    ),
                    "max_idle_count": max(
                        (r["n"] for s in samples for r in s if r["state"] == "idle in transaction"),
                        default=0,
                    ),
                }
                save(f"login-{label}-{count}", report)
                assert len(codes) == count and set(codes) == {200}
            finally:
                stop.set()
                if pending is not None:
                    pending.cancel()
                    await asyncio.gather(pending, return_exceptions=True)
                if sampler is not None:
                    await sampler
                await asyncio.gather(*(c.aclose() for c in clients))
            await asyncio.sleep(0.5)
    finally:
        await ordinary.aclose()
        await get_engine().dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--bursts", type=int, nargs="+", default=[8, 32, 64])
    args = parser.parse_args()
    asyncio.run(run(args.label, args.bursts))

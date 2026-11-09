"""Synthetic failure probes. Restart choreography belongs to the host, never the API.

Run duplicate and timeout directly in the probe container. For restart, run
prepare-restart, kill/start ONLY kap-capacity-local-light-1, then finish-restart.
The configured 30s lease accelerates recovery; it is not a production RTO claim.
"""

import argparse
import asyncio
import json
import time
import uuid
from types import SimpleNamespace

import httpx
from capacity_common import FIXTURE, guard
from capacity_probe import ROOT, client, drain, get_engine, get_sessionmaker, login, save, uploads
from sqlalchemy import func, select

guard()
from app.models.ingest import IngestTask, IngestTaskAiResult  # noqa: E402
from app.worker.tasks.ingest import process_ingest_upload  # noqa: E402


async def control(delay=None):
    async with httpx.AsyncClient(trust_env=False) as c:
        response = (
            await c.get(FIXTURE + "/control")
            if delay is None
            else await c.post(FIXTURE + "/control", json={"llm_delay": delay})
        )
        response.raise_for_status()
        return response.json()


async def latest():
    key = json.loads((ROOT / "latest-tasks.json").read_text())[0]
    async with get_sessionmaker()() as session:
        task = await session.get(IngestTask, uuid.UUID(key))
        return key, {
            "status": task.status,
            "stage": task.processing_stage,
            "error": task.error_type,
            "attempt": task.processing_attempt,
            "retry_count": task.retry_count,
        }


async def main(mode):
    try:
        started = time.monotonic()
        if mode != "finish-restart":
            before = await control(
                45 if mode == "prepare-restart" else 8 if mode == "timeout" else 3
            )
            await uploads(SimpleNamespace(count=1, submit_only=True))
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                current = await control()
                if current["inflight"].get("content", 0):
                    break
                await asyncio.sleep(0.1)
            else:
                raise RuntimeError("No live content request observed")
            key, state = await latest()
            assert state["status"] == "processing", state
            if mode == "prepare-restart":
                save(
                    "restart-before",
                    {
                        "task_id": key,
                        "state": state,
                        "content_calls": current["counts"].get("content", 0),
                    },
                )
                return
            if mode == "duplicate":
                for _ in range(3):
                    process_ingest_upload.apply_async(args=[key], queue="default")
            else:
                while time.monotonic() - started < 30:
                    _, state = await latest()
                    if state["status"] == "failed":
                        break
                    await asyncio.sleep(0.2)
                assert state["status"] == "failed" and state["error"] == "timeout", state
                save(
                    "timeout-terminal",
                    {
                        "passed": True,
                        "state": state,
                        "elapsed_seconds": round(time.monotonic() - started, 2),
                    },
                )
                await control(0.05)
        else:
            key, state = await latest()
            await control(0.05)
        async with client() as c:
            await login(c, 0)
            if mode == "timeout":
                response = await c.post(f"/api/v1/ingest/{key}/retry")
                response.raise_for_status()
            await drain(c, [key], started)
        async with get_sessionmaker()() as session:
            result_count = await session.scalar(
                select(func.count())
                .select_from(IngestTaskAiResult)
                .where(IngestTaskAiResult.ingest_task_id == uuid.UUID(key))
            )
        assert result_count == 1
        current = await control(0.05)
        key, state = await latest()
        if mode == "duplicate":
            assert current["counts"]["content"] - before["counts"].get("content", 0) == 1, current
        save(
            f"fault-{mode}",
            {
                "passed": True,
                "state": state,
                "ai_results": result_count,
                "unique_asset_confirmed_and_indexed": True,
                "elapsed_seconds": round(time.monotonic() - started, 2),
            },
        )
    finally:
        if mode != "prepare-restart":
            await control(0.05)
        await get_engine().dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode", choices=["duplicate", "timeout", "prepare-restart", "finish-restart"]
    )
    asyncio.run(main(parser.parse_args().mode))

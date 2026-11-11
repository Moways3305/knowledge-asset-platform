"""Process-local measurements for the guarded synthetic API only.

No SQL text, request bodies, credentials or user identifiers are recorded.
Pool acquisition includes creating/preparing a connection as well as queue wait;
SQL timings include driver/event-loop waiting, not just PostgreSQL execution.
"""

import asyncio
import json
import os
import time
import uuid
from contextvars import ContextVar
from pathlib import Path

import httpx
from capacity_common import guard
from capacity_metric_stream import MetricBuffer, append_frame
from celery.signals import before_task_publish, task_postrun, task_prerun
from sqlalchemy import event

guard()
MODE = os.environ.get("KAP_CAPACITY_API_METRICS", "stream")
if MODE not in {"stream", "off"}:
    raise ValueError("KAP_CAPACITY_API_METRICS must be stream or off")
route = ContextVar("capacity_route", default="other")
buffer = MetricBuffer(started=time.monotonic())
task_starts = {}


@before_task_publish.connect
def published(headers=None, **kwargs):
    if headers is not None:
        headers["capacity_published_at"] = time.time()


@task_prerun.connect
def task_started(task_id=None, task=None, **kwargs):
    sent = (task.request.headers or {}).get("capacity_published_at")
    task_starts[task_id] = (
        time.perf_counter(),
        {
            "task": task.name,
            "queue": task.request.delivery_info.get("routing_key"),
            "queue_seconds": max(0, time.time() - sent) if sent is not None else None,
            "started_at": time.time(),
        },
    )


@task_postrun.connect
def task_finished(task_id=None, state=None, **kwargs):
    started, row = task_starts.pop(task_id)
    row.update(runtime_seconds=time.perf_counter() - started, state=state)
    with Path(f"/capacity/worker-metrics-{os.getpid()}.jsonl").open("a") as output:
        output.write(json.dumps(row) + "\n")


def record(kind, elapsed):
    record_value(f"{route.get()}.{kind}", round(elapsed * 1000, 3))


def record_value(key, value):
    buffer.add(key, value, time.monotonic())


def install(engine):
    password_delay = float(os.environ.get("KAP_CAPACITY_PASSWORD_DELAY", "0"))
    assert 0 <= password_delay <= 2
    if password_delay:
        from app.services import passwords

        compute = passwords._pbkdf2

        def delayed_hash(*args):
            # Controlled CPU-worker wait; the real password hash still runs.
            # This changes only the isolated harness, never the app executor.
            time.sleep(password_delay)
            return compute(*args)

        passwords._pbkdf2 = delayed_hash

    if MODE == "off":
        return

    # Test harness only. QueuePool has no public before-checkout event. Wrap its
    # acquisition boundary so queueing is measured separately from holding it.
    acquire = engine.pool._do_get

    def measured_acquire():
        started = time.perf_counter()
        try:
            return acquire()
        finally:
            record("pool_acquire_ms", time.perf_counter() - started)

    engine.pool._do_get = measured_acquire
    send = httpx.AsyncClient.send

    async def measured_send(client, request, **kwargs):
        kind = "foundation"
        if request.url.path.endswith("chat/completions"):
            system = json.loads(request.content)["messages"][0].get("content", "")
            kind = (
                "planning"
                if '"queries"' in system
                else "answer"
                if "answer_parts" in system
                else "rerank"
                if '"order"' in system
                else "model"
            )
        started = time.perf_counter()
        try:
            return await send(client, request, **kwargs)
        finally:
            record(kind + "_http_ms", time.perf_counter() - started)

    httpx.AsyncClient.send = measured_send

    @event.listens_for(engine, "checkout")
    def checkout(connection, rec, proxy):
        rec.info["capacity_checkout"] = (time.perf_counter(), route.get())

    @event.listens_for(engine, "checkin")
    def checkin(connection, rec):
        stamp = rec.info.pop("capacity_checkout", None)
        if stamp:
            record_value(
                f"{stamp[1]}.pool_hold_ms", round((time.perf_counter() - stamp[0]) * 1000, 3)
            )

    @event.listens_for(engine, "before_cursor_execute")
    def before(conn, cursor, statement, parameters, context, executemany):
        context.capacity_started = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def after(conn, cursor, statement, parameters, context, executemany):
        record("sql_ms", time.perf_counter() - context.capacity_started)


class MeasuredAPI:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if MODE == "off":
            return await self.app(scope, receive, send)
        if scope["type"] == "lifespan":
            sampler = asyncio.create_task(self.sample())
            try:
                return await self.app(scope, receive, send)
            finally:
                sampler.cancel()
                await asyncio.gather(sampler, return_exceptions=True)
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        label = (
            "qa"
            if path.endswith("/qa")
            else "search"
            if path.endswith("/knowledge/search")
            else "login"
            if path.endswith("/auth/login")
            else "list"
            if path == "/api/v1/knowledge"
            else "upload"
            if path.endswith("/ingest/upload")
            else "other"
        )
        token = route.set(label)
        started = time.perf_counter()
        try:
            return await self.app(scope, receive, send)
        finally:
            record("request_ms", time.perf_counter() - started)
            route.reset(token)

    async def sample(self):
        tick = time.perf_counter()
        path = Path(f"/capacity/api-metrics-{os.getpid()}-{uuid.uuid4().hex}.jsonl")

        async def flush():
            while True:
                await asyncio.sleep(1)
                frame = buffer.drain(time.monotonic())
                await asyncio.to_thread(append_frame, path, frame)

        writer = asyncio.create_task(flush())
        try:
            while True:
                await asyncio.sleep(0.1)
                now = time.perf_counter()
                record_value("event_loop_lag_ms", round(max(0, now - tick - 0.1) * 1000, 3))
                tick = now
        finally:
            # Writer I/O waits are not event-loop lag. A separate heartbeat can
            # still observe scheduling stalls while serialization is in flight.
            writer.cancel()
            await asyncio.gather(writer, return_exceptions=True)

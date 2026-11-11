"""Guarded outbox transaction/connection timings, without SQL or payload logging."""

import json
import os
import time
from pathlib import Path

from capacity_worker import celery_app, runtime  # noqa: F401
from celery import current_task
from sqlalchemy import event

_create = runtime.create_async_engine


def measured_engine(*args, **kwargs):
    engine = _create(*args, **kwargs)
    task_name = getattr(current_task, "name", None)

    def record(kind, started):
        if started:
            with Path(f"/capacity/outbox-transactions-{os.getpid()}.jsonl").open("a") as output:
                output.write(
                    json.dumps(
                        {
                            "task": task_name,
                            "kind": kind,
                            "at": time.time(),
                            "seconds": time.monotonic() - started,
                        }
                    )
                    + "\n"
                )

    @event.listens_for(engine.sync_engine, "begin")
    def begin(conn):
        conn.info["outbox_tx"] = time.monotonic()

    @event.listens_for(engine.sync_engine, "commit")
    @event.listens_for(engine.sync_engine, "rollback")
    def finish(conn):
        record("transaction", conn.info.pop("outbox_tx", None))

    @event.listens_for(engine.sync_engine, "checkout")
    def checkout(dbapi, rec, proxy):
        rec.info["outbox_hold"] = time.monotonic()

    @event.listens_for(engine.sync_engine, "checkin")
    def checkin(dbapi, rec):
        record("connection", rec.info.pop("outbox_hold", None))

    return engine


runtime.create_async_engine = measured_engine

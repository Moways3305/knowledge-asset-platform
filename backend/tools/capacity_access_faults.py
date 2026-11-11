"""Opt-in isolated worker that pauses a chosen decision before its atomic commit."""

import asyncio
import json
import os
from pathlib import Path

from capacity_common import guard
from capacity_worker import celery_app  # noqa: F401

guard()

from app.services.jobs import original_access_scan  # noqa: E402

_commit = original_access_scan._commit_item


async def pause(session, run, key):
    control = Path("/capacity/access-pause")
    if control.exists() and control.read_text().strip() == str(key[1]):
        Path("/capacity/access-paused.json").write_text(
            json.dumps({"pid": os.getpid(), "ready": True})
        )
        while control.exists():
            await asyncio.sleep(0.05)
    await _commit(session, run, key)


original_access_scan._commit_item = pause

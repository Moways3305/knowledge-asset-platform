"""Opt-in isolated fault: stop after staging a second page, before its commit."""

import asyncio
import json
import os
from pathlib import Path

from capacity_common import guard
from capacity_outbox_worker import celery_app  # noqa: F401

guard()

from app.services import outbox  # noqa: E402

_dispatch = outbox._dispatch


async def pause(session, row):
    page = await _dispatch(session, row)
    control = Path("/capacity/outbox-pause")
    if (
        row.recipient_cursor is not None
        and control.exists()
        and control.read_text().strip() == str(row.id)
    ):
        await session.flush()
        Path("/capacity/outbox-paused.json").write_text(
            json.dumps({"pid": os.getpid(), "ready": True, "event_id": str(row.id)})
        )
        while control.exists():
            await asyncio.sleep(0.05)
    return page


# Only this opt-in fault worker suspends the normal five-second page timeout,
# giving the operator time to kill the paused child. Never used for timing runs.
outbox.PAGE_SECONDS = 120
outbox._dispatch = pause

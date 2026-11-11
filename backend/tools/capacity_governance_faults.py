"""Opt-in disposable consumer for deterministic child-loss recovery verification.

Use instead of capacity_worker ONLY in the guarded isolated environment. The
host writes /capacity/governance-pause containing archive, review or reuse, waits for
governance-paused.json, kills that child, then removes the pause and resumes.
"""

import asyncio
import json
import os
from pathlib import Path

from capacity_common import guard
from capacity_worker import celery_app  # noqa: F401

guard()

from app.services.jobs import governance_scan  # noqa: E402

_finish = governance_scan.finish_batch


async def _pause_before_commit(session, run, processed, *conditions):
    control = Path("/capacity/governance-pause")
    if processed and control.exists() and control.read_text().strip() == run.name:
        Path("/capacity/governance-paused.json").write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "kind": run.name,
                    "staged_assets": len(processed),
                }
            )
        )
        while control.exists():
            await asyncio.sleep(0.05)
    await _finish(session, run, processed, *conditions)


governance_scan.finish_batch = _pause_before_commit

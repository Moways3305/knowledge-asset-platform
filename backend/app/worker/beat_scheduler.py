"""Celery beat scheduler that records a heartbeat from the beat process itself."""

from __future__ import annotations

import logging
import time

from celery.beat import PersistentScheduler

from app.core.config import get_settings
from app.core.logging import safe_log_exception
from app.worker.runtime import run_task

_logger = logging.getLogger(__name__)
_HEARTBEAT_INTERVAL_SECONDS = 60.0


async def _record(maker) -> None:
    from app.services.indexing_health import record_heartbeat

    async with maker() as session:
        await record_heartbeat(session, "beat")


def record_beat_heartbeat_from_scheduler() -> bool:
    """Called only by the beat scheduler process; eager mode never claims liveness."""
    if get_settings().celery_task_always_eager:
        return False
    run_task(_record, label="ops.beat_heartbeat")
    return True


class DatabaseHeartbeatScheduler(PersistentScheduler):
    def setup_schedule(self) -> None:
        self._last_database_heartbeat = 0.0
        super().setup_schedule()

    def tick(self, *args, **kwargs):
        now = time.monotonic()
        if now - self._last_database_heartbeat >= _HEARTBEAT_INTERVAL_SECONDS:
            try:
                record_beat_heartbeat_from_scheduler()
            except Exception as exc:  # sampling must never stop beat
                safe_log_exception(
                    _logger,
                    "beat_heartbeat_failed",
                    exc,
                    include_summary=False,
                    level=logging.WARNING,
                )
            self._last_database_heartbeat = now
        return super().tick(*args, **kwargs)

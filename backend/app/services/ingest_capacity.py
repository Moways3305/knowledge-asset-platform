"""Cross-worker execution slots. PostgreSQL releases slots when the connection dies.

Transaction-scoped advisory locks use a dedicated, read-only transaction; normal
processing commits cannot release the slots. No task bytes are loaded before admission.
"""

from contextlib import asynccontextmanager

from sqlalchemy import text

from app.core.config import get_settings
from app.models.ingest import IngestTask

_GENERAL_LOCK = 1262571600
_HEAVY_LOCK = 1262571700


async def _take_slot(session, namespace: int, capacity: int) -> bool:
    for slot in range(capacity):
        if await session.scalar(
            text("SELECT pg_try_advisory_xact_lock(:namespace, :slot)"),
            {"namespace": namespace, "slot": slot},
        ):
            return True
    return False


@asynccontextmanager
async def processing_slot(maker, task_id):
    async with maker() as gate:
        # Local SQLite/eager execution is serial. Production uses PostgreSQL.
        if gate.get_bind().dialect.name != "postgresql":
            yield True
            return
        settings = get_settings()
        try:
            task = await gate.get(IngestTask, task_id)
            if task is None or task.cancel_requested or task.status == "cancelled":
                yield True  # Let the existing cancellation/terminal handler acknowledge it.
                return
            admitted = await _take_slot(gate, _GENERAL_LOCK, settings.ingest_processing_window)
            content_only = task.processing_stage in {
                "canonical_markdown_generation",
                "content_generation_queued",
                "content_generation",
                "waiting_generation_config",
                "content_generation_failed",
            }
            heavy = not content_only and not task.source_file_name.lower().endswith(
                (".txt", ".md", ".markdown")
            )
            if admitted and heavy:
                admitted = await _take_slot(
                    gate, _HEAVY_LOCK, settings.ingest_heavy_processing_window
                )
            yield admitted
        finally:
            await gate.rollback()

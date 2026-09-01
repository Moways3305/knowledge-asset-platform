"""Dry-run-first recovery command for the 2026-08-31 OCR incident.

Usage inside the backend container::

    python -m app.commands.recover_ocr_incident
    python -m app.commands.recover_ocr_incident --apply --confirm-ocr-ready \
      --memory-events-path /sys/fs/cgroup/memory.events
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.ingest import IngestTask
from app.services.jobs.ingest_recovery import recover_stale_tasks
from app.services.storage import get_storage


def _oom_kill_count(path: Path | None) -> int | None:
    if path is None:
        return None
    try:
        values = dict(
            line.split(maxsplit=1) for line in path.read_text(encoding="utf-8").splitlines()
        )
        return int(values.get("oom_kill", "0"))
    except (OSError, ValueError):
        return None


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        before_oom = _oom_kill_count(args.memory_events_path)
        selected_ids = tuple(args.task_id[:31]) if args.task_id else None
        remaining = min(max(1, args.limit), len(selected_ids) if selected_ids else 31, 31)
        totals = {
            "scanned": 0,
            "scheduled": 0,
            "source_unavailable": 0,
            "exhausted": 0,
            "already_succeeded": 0,
            "not_processing": 0,
        }
        if selected_ids:
            async with maker() as session:
                selected = (
                    (
                        await session.execute(
                            select(IngestTask).where(IngestTask.id.in_(selected_ids))
                        )
                    )
                    .scalars()
                    .all()
                )
            totals["already_succeeded"] = sum(
                task.status in {"pending_confirmation", "completed"} for task in selected
            )
            totals["not_processing"] = len(selected_ids) - sum(
                task.status == "processing" for task in selected
            )
        while remaining > 0:
            current_oom = _oom_kill_count(args.memory_events_path)
            if before_oom is not None and current_oom is not None and current_oom > before_oom:
                print(json.dumps({**totals, "stopped": "new_oom_kill"}, ensure_ascii=False))
                return 2
            batch = remaining if not args.apply else min(remaining, max(1, args.batch_size))
            async with maker() as session:
                summary = await recover_stale_tasks(
                    session,
                    get_storage(),
                    limit=batch,
                    dry_run=not args.apply,
                    task_ids=selected_ids,
                )
            totals["scanned"] += summary.scanned
            totals["source_unavailable"] += summary.source_unavailable
            totals["exhausted"] += summary.exhausted
            if args.apply:
                from app.worker.tasks.ingest import process_ingest_upload

                for item in summary.scheduled:
                    process_ingest_upload.apply_async(
                        args=[str(item.task_id), f"incident-recovery-{item.task_id}"],
                        queue=item.queue,
                        countdown=item.countdown,
                    )
                totals["scheduled"] += len(summary.scheduled)
            else:
                totals["scheduled"] += len(summary.scheduled)
            if summary.scanned == 0 or not args.apply:
                break
            remaining -= summary.scanned
            if remaining > 0:
                time.sleep(max(0, args.batch_pause_seconds))
        print(
            json.dumps({**totals, "mode": "apply" if args.apply else "dry-run"}, ensure_ascii=False)
        )
        return 0
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Classify/recover at most 31 stale OCR incident tasks"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="persist audited classifications and enqueue recoverable work",
    )
    parser.add_argument(
        "--confirm-ocr-ready",
        action="store_true",
        help="assert the limited OCR worker passed a single-file smoke test",
    )
    parser.add_argument("--limit", type=int, default=31)
    parser.add_argument(
        "--task-id",
        action="append",
        type=uuid.UUID,
        default=[],
        help="exact incident UUID; repeat up to 31 times to classify terminal tasks too",
    )
    parser.add_argument("--batch-size", type=int, default=3)
    parser.add_argument("--batch-pause-seconds", type=int, default=15)
    parser.add_argument("--memory-events-path", type=Path)
    args = parser.parse_args()
    if args.apply and not args.confirm_ocr_ready:
        parser.error("--apply requires --confirm-ocr-ready after the limited OCR worker smoke test")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())

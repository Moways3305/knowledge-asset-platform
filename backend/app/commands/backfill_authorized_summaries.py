"""Dry-run-first command for complete L2–L4 authorized summary backfill."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from collections.abc import Sequence
from dataclasses import asdict

from app.db.session import get_engine, get_sessionmaker
from app.services.authorized_summary_backfill import backfill_authorized_summaries


async def _run(*, dry_run: bool, asset_id: uuid.UUID | None = None) -> dict[str, object]:
    try:
        async with get_sessionmaker()() as session:
            report = await backfill_authorized_summaries(
                session, dry_run=dry_run, asset_id=asset_id
            )
            return asdict(report)
    finally:
        await get_engine().dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate complete L2–L4 authorized summaries. Defaults to dry-run."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist changes. Without this flag, only content-free counts and lengths are printed.",
    )
    parser.add_argument(
        "--asset-id", type=uuid.UUID, help="Repair only this asset's current version."
    )
    args = parser.parse_args(argv)
    print(
        json.dumps(
            asyncio.run(_run(dry_run=not args.apply, asset_id=args.asset_id)), ensure_ascii=False
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

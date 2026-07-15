"""Run the one-time first-general-manager bootstrap without echoing identity details."""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid
from collections.abc import Sequence

from app.db.session import get_sessionmaker
from app.services.governance_bootstrap import BossBootstrapResult, bootstrap_first_boss

_TARGET_ENV = "KAP_BOOTSTRAP_BOSS_TARGET_USER_ID"


def _parse_target(argv: Sequence[str] | None) -> str:
    parser = argparse.ArgumentParser(
        description="Bootstrap the first general manager from an existing active user."
    )
    parser.add_argument(
        "--user-id",
        dest="target_user_id",
        help=f"Target user UUID. Defaults to {_TARGET_ENV}.",
    )
    args = parser.parse_args(argv)
    return (args.target_user_id or os.environ.get(_TARGET_ENV) or "").strip()


async def _run(target_user_id: uuid.UUID) -> BossBootstrapResult:
    async with get_sessionmaker()() as session:
        return await bootstrap_first_boss(
            session,
            target_user_id=target_user_id,
            trace_id=f"boss-bootstrap-{uuid.uuid4().hex}",
        )


def main(argv: Sequence[str] | None = None) -> int:
    raw_target = _parse_target(argv)
    try:
        target_user_id = uuid.UUID(raw_target)
    except ValueError:
        print("boss_bootstrap_invalid_target")
        return 2

    result = asyncio.run(_run(target_user_id))
    print(result.value)
    return 0 if result is BossBootstrapResult.created else 3


if __name__ == "__main__":
    raise SystemExit(main())

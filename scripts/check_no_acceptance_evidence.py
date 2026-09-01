"""Reject local acceptance artifacts that were force-added despite .gitignore."""

from __future__ import annotations

import sys
import subprocess
from pathlib import PurePath


FORBIDDEN_PREFIX = ("docs", "claude_tasks", "evidence")


def is_forbidden(filename: str) -> bool:
    parts = PurePath(filename.replace("\\", "/")).parts
    return tuple(part.lower() for part in parts[:3]) == FORBIDDEN_PREFIX


def main(filenames: list[str]) -> int:
    if filenames == ["--tracked"]:
        tracked = subprocess.run(
            ["git", "ls-files", "-z", "--", "docs/claude_tasks/evidence"],
            check=True,
            capture_output=True,
        ).stdout
        filenames = [filename.decode("utf-8") for filename in tracked.split(b"\0") if filename]
    forbidden = [filename for filename in filenames if is_forbidden(filename)]
    if not forbidden:
        return 0
    print(
        "Acceptance screenshots and reports are local-only; remove these paths from Git:",
        file=sys.stderr,
    )
    for filename in forbidden:
        print(f"  {filename}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

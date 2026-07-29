"""Build the self-contained stdio connector executable with PyInstaller."""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--work-dir", required=True)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    output = Path(args.output_dir).resolve()
    work = Path(args.work_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    expected_arch = os.environ.get("CONNECTOR_ARCH")
    actual_arch = platform.machine().lower()
    aliases = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}
    if expected_arch and aliases.get(actual_arch, actual_arch) != expected_arch:
        raise SystemExit(
            f"runner architecture {actual_arch!r} does not match target {expected_arch!r}"
        )

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "kap-workbuddy-connector",
        "--distpath",
        str(output),
        "--workpath",
        str(work / "pyinstaller"),
        "--specpath",
        str(work),
        "--collect-all",
        "mcp",
        "--collect-submodules",
        "workbuddy_mcp",
        str(root / "connector_entry.py"),
    ]
    subprocess.run(command, cwd=root, check=True)


if __name__ == "__main__":
    main()

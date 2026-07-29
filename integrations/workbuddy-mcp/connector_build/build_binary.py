"""Build the self-contained stdio connector executable with PyInstaller."""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path

EXECUTABLE_NAME = "kap-workbuddy-connector"


def expected_binary_path(output_dir: Path, *, system: str | None = None) -> Path:
    """Return the single platform binary path promised to installer scripts."""
    suffix = ".exe" if (system or platform.system()).lower() == "windows" else ""
    return output_dir.resolve() / f"{EXECUTABLE_NAME}{suffix}"


def build_binary(output_dir: Path, work_dir: Path) -> Path:
    root = Path(__file__).resolve().parents[1]
    output = output_dir.resolve()
    work = work_dir.resolve()
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
        EXECUTABLE_NAME,
        "--distpath",
        str(output),
        "--workpath",
        str(work / "pyinstaller"),
        "--specpath",
        str(work),
        "--collect-submodules",
        "mcp.server",
        "--collect-submodules",
        "workbuddy_mcp",
        str(root / "connector_entry.py"),
    ]
    try:
        subprocess.run(command, cwd=root, check=True)
    except subprocess.CalledProcessError:
        target = f"{platform.system().lower()}-{expected_arch or 'native'}"
        raise SystemExit(f"connector binary build failed for {target}") from None
    binary = expected_binary_path(output)
    if not binary.is_file() or binary.stat().st_size == 0:
        raise SystemExit(f"missing or empty connector binary for {platform.system().lower()}")
    return binary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--work-dir", required=True)
    args = parser.parse_args()
    build_binary(Path(args.output_dir), Path(args.work_dir))


if __name__ == "__main__":
    main()

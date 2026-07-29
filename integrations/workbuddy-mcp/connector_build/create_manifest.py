"""Create the public connector manifest from secret-free build metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_TARGETS = {("windows", "x64"), ("macos", "arm64"), ("macos", "x64")}


def create_manifest(source: Path, output: Path, *, version: str, channel: str) -> dict:
    if not _VERSION.fullmatch(version):
        raise ValueError("version must be semantic and filesystem-safe")
    if channel not in {"production", "internal"}:
        raise ValueError("channel must be production or internal")
    output.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict] = []
    targets: set[tuple[str, str]] = set()
    for metadata_path in sorted(source.rglob("*.metadata.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        target = (metadata.get("platform"), metadata.get("architecture"))
        if target not in _TARGETS or target in targets:
            raise ValueError("unexpected or duplicate connector target")
        filename = metadata.get("filename")
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ValueError("unsafe artifact filename")
        artifact_path = metadata_path.parent / filename
        if not artifact_path.is_file():
            raise ValueError("artifact declared by metadata is missing")
        signed = metadata.get("signed") is True
        notarized = metadata.get("notarized") is True
        if channel == "production":
            if target[0] == "windows" and not signed:
                raise ValueError("production Windows artifact must be signed")
            if target[0] == "macos" and (not signed or not notarized):
                raise ValueError("production macOS artifact must be signed and notarized")
        destination = output / filename
        shutil.copy2(artifact_path, destination)
        artifacts.append(
            {
                "platform": target[0],
                "architecture": target[1],
                "filename": filename,
                "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
                "signed": signed,
                "notarized": notarized,
            }
        )
        targets.add(target)
    if targets != _TARGETS:
        raise ValueError("all Windows x64, macOS arm64 and macOS x64 artifacts are required")
    manifest = {"version": version, "channel": channel, "artifacts": artifacts}
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--channel", choices=("production", "internal"), required=True)
    args = parser.parse_args()
    create_manifest(args.source, args.output, version=args.version, channel=args.channel)


if __name__ == "__main__":
    main()

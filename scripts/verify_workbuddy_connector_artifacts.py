"""Verify a production or explicitly allowed internal WorkBuddy Connector artifact set.

The command prints only a safe version/target summary. It never reads application credentials,
user data or token-bearing MCP configuration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_TARGETS = {("windows", "x64"), ("macos", "arm64"), ("macos", "x64")}
_TRUSTED_REPOSITORY = "Moways3305/knowledge-asset-platform"
_TRUSTED_SIGNER_WORKFLOW = (
    f"{_TRUSTED_REPOSITORY}/.github/workflows/workbuddy-connector-trusted-builder.yml"
)
_TRUSTED_CERT_IDENTITY = f"https://github.com/{_TRUSTED_SIGNER_WORKFLOW}@refs/heads/main"
_PREDICATE_TYPE = (
    "https://github.com/Moways3305/knowledge-asset-platform/"
    "attestations/workbuddy-connector-signature/v1"
)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_attestation(
    path: Path,
    *,
    expected_predicate: dict,
) -> None:
    command = [
        "gh",
        "attestation",
        "verify",
        str(path),
        "--repo",
        _TRUSTED_REPOSITORY,
        "--signer-workflow",
        _TRUSTED_SIGNER_WORKFLOW,
        "--cert-identity",
        _TRUSTED_CERT_IDENTITY,
        "--source-ref",
        "refs/heads/main",
        "--deny-self-hosted-runners",
        "--predicate-type",
        _PREDICATE_TYPE,
        "--format",
        "json",
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("trusted release attestation could not be verified") from exc
    if result.returncode != 0:
        raise ValueError("trusted release attestation could not be verified")
    try:
        verifications = json.loads(result.stdout)
        predicates = [
            item["verificationResult"]["statement"]["predicate"] for item in verifications
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("trusted release attestation response is invalid") from exc
    if not any(
        isinstance(predicate, dict)
        and all(predicate.get(key) == value for key, value in expected_predicate.items())
        for predicate in predicates
    ):
        raise ValueError("trusted release attestation predicate is invalid")


def verify_artifact_root(root: Path, *, allow_internal: bool = False) -> dict:
    root = root.resolve()
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError("manifest.json is missing or invalid") from exc
    if not isinstance(manifest, dict):
        raise ValueError("manifest.json is missing or invalid")
    version = manifest.get("version")
    if not isinstance(version, str) or not _VERSION.fullmatch(version):
        raise ValueError("manifest version is invalid")
    channel = manifest.get("channel")
    if channel not in {"production", "internal"}:
        raise ValueError("manifest channel is invalid")
    if channel == "internal" and not allow_internal:
        raise ValueError("only channel=production may be deployed")
    if channel == "production":
        _verify_attestation(
            root / "manifest.json",
            expected_predicate={"channel": "production", "complete": True},
        )
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("manifest artifacts must be a list")

    targets: set[tuple[str, str]] = set()
    expected_entries = {"manifest.json"}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ValueError("artifact entry is invalid")
        target = (artifact.get("platform"), artifact.get("architecture"))
        if target not in _TARGETS or target in targets:
            raise ValueError("artifact target is missing, duplicate or unsupported")
        filename = artifact.get("filename")
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise ValueError("artifact filename is unsafe")
        expected_entries.add(filename)
        path = (root / filename).resolve()
        if root not in path.parents or not path.is_file():
            raise ValueError("artifact file is missing")
        expected = artifact.get("sha256")
        if not isinstance(expected, str) or not _SHA256.fullmatch(expected):
            raise ValueError("artifact checksum is invalid")
        if _file_sha256(path) != expected:
            raise ValueError("artifact checksum mismatch")
        if channel == "production":
            if target[0] == "windows" and artifact.get("signed") is not True:
                raise ValueError("production Windows artifact is not signed")
            if target[0] == "macos" and (
                artifact.get("signed") is not True or artifact.get("notarized") is not True
            ):
                raise ValueError("production macOS artifact is not signed and notarized")
            expected_predicate = (
                {"platform": "windows", "authenticode_verified": True}
                if target[0] == "windows"
                else {
                    "platform": "macos",
                    "developer_id_verified": True,
                    "notarization_stapled_verified": True,
                }
            )
            _verify_attestation(
                path,
                expected_predicate=expected_predicate,
            )
        elif artifact.get("signed") is not False or artifact.get("notarized") is not False:
            raise ValueError("internal artifacts must declare signed=false and notarized=false")
        targets.add(target)
    if targets != _TARGETS:
        raise ValueError("all three connector targets are required")
    if {path.name for path in root.iterdir()} != expected_entries:
        raise ValueError("artifact root must contain only the manifest and three installers")
    return {
        "version": version,
        "channel": channel,
        "targets": ["macos-arm64", "macos-x64", "windows-x64"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument(
        "--allow-internal",
        action="store_true",
        help="allow a complete unsigned channel=internal enterprise artifact set",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            verify_artifact_root(args.root, allow_internal=args.allow_internal),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

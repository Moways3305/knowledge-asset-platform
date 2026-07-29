from __future__ import annotations

import json

import pytest
from connector_build.create_manifest import create_manifest


def _target(root, platform, architecture, *, signed, notarized):
    suffix = ".exe" if platform == "windows" else ".pkg"
    filename = f"connector-{platform}-{architecture}{suffix}"
    (root / filename).write_bytes(f"{platform}-{architecture}".encode())
    (root / f"{filename}.metadata.json").write_text(
        json.dumps(
            {
                "platform": platform,
                "architecture": architecture,
                "filename": filename,
                "signed": signed,
                "notarized": notarized,
            }
        ),
        encoding="utf-8",
    )


def _all_targets(root, *, signed):
    _target(root, "windows", "x64", signed=signed, notarized=False)
    _target(root, "macos", "arm64", signed=signed, notarized=signed)
    _target(root, "macos", "x64", signed=signed, notarized=signed)


def test_internal_manifest_has_three_versioned_checksums_and_no_credentials(tmp_path):
    source = tmp_path / "source"
    output = tmp_path / "output"
    source.mkdir()
    _all_targets(source, signed=False)
    manifest = create_manifest(source, output, version="1.2.3", channel="internal")
    assert len(manifest["artifacts"]) == 3
    assert all(len(item["sha256"]) == 64 for item in manifest["artifacts"])
    blob = json.dumps(manifest)
    for leak in ("KAP_AGENT_TOKEN", "Authorization", "APPLE_APP_PASSWORD", "user_id"):
        assert leak not in blob


def test_production_manifest_rejects_unsigned_artifacts(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _all_targets(source, signed=False)
    with pytest.raises(ValueError, match="must be signed"):
        create_manifest(source, tmp_path / "output", version="1.2.3", channel="production")


def test_production_manifest_accepts_signed_and_notarized_targets(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    _all_targets(source, signed=True)
    manifest = create_manifest(source, tmp_path / "output", version="1.2.3", channel="production")
    assert manifest["channel"] == "production"

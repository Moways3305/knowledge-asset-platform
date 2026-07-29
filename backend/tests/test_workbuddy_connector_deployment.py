"""Production connector mount and host artifact verifier contracts."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
OVERLAY = ROOT / "docker-compose.prod.yml"
VERIFY_SCRIPT = ROOT / "scripts" / "verify_workbuddy_connector_artifacts.py"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "workbuddy-connector-release.yml"
TRUSTED_BUILDER = ROOT / ".github" / "workflows" / "workbuddy-connector-trusted-builder.yml"


def _load_verifier():
    spec = importlib.util.spec_from_file_location(
        "verify_workbuddy_connector_artifacts", VERIFY_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _production_root(root: Path):
    artifacts = []
    for platform, architecture, suffix in (
        ("windows", "x64", ".exe"),
        ("macos", "arm64", ".pkg"),
        ("macos", "x64", ".pkg"),
    ):
        filename = f"connector-{platform}-{architecture}{suffix}"
        payload = f"{platform}-{architecture}".encode()
        (root / filename).write_bytes(payload)
        artifacts.append(
            {
                "platform": platform,
                "architecture": architecture,
                "filename": filename,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "signed": True,
                "notarized": platform == "macos",
            }
        )
    (root / "manifest.json").write_text(
        json.dumps({"version": "1.2.3", "channel": "production", "artifacts": artifacts}),
        encoding="utf-8",
    )
    return artifacts


def _trust_release_attestations(verifier, monkeypatch):
    verified = []

    def trust(path, **kwargs):
        verified.append((path.name, kwargs["expected_predicate"]))

    monkeypatch.setattr(verifier, "_verify_attestation", trust)
    return verified


def _verify_root(verifier, root: Path):
    return verifier.verify_artifact_root(root)


def test_production_overlay_mounts_connector_root_read_only_only_on_backend():
    text = OVERLAY.read_text(encoding="utf-8")
    assert "WORKBUDDY_CONNECTOR_ARTIFACT_ROOT: /data/workbuddy-connectors" in text
    assert "/data/kap/workbuddy-connectors:/data/workbuddy-connectors:ro" in text
    assert text.count("/data/workbuddy-connectors") == 2
    for service in ("worker:", "beat:", "frontend:", "postgres:", "redis:"):
        assert service not in text


def test_only_main_branch_trusted_builder_can_attest_signature_state():
    release = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    trusted = TRUSTED_BUILDER.read_text(encoding="utf-8")

    assert "actions/attest@" not in release
    assert (
        "Moways3305/knowledge-asset-platform/.github/workflows/"
        "workbuddy-connector-trusted-builder.yml@main"
    ) in release
    assert "github.ref != 'refs/heads/main'" in release
    assert "signtool verify /pa" in trusted
    assert "pkgutil --check-signature" in trusted
    assert "xcrun stapler validate" in trusted
    assert "spctl --assess --type install" in trusted
    assert trusted.count("uses: actions/attest@v4") == 3
    assert "ref: main" in trusted
    for secret_name in (
        "WINDOWS_SIGNING_PFX_BASE64",
        "WINDOWS_SIGNING_PFX_PASSWORD",
        "APPLE_CERTIFICATES_P12_BASE64",
        "APPLE_APP_PASSWORD",
    ):
        assert secret_name not in trusted


def test_host_verifier_accepts_complete_attested_production_set(tmp_path, monkeypatch):
    artifacts = _production_root(tmp_path)
    verifier = _load_verifier()
    verified = _trust_release_attestations(verifier, monkeypatch)
    result = _verify_root(verifier, tmp_path)
    assert result == {
        "version": "1.2.3",
        "channel": "production",
        "targets": ["macos-arm64", "macos-x64", "windows-x64"],
    }
    assert {name for name, _predicate in verified} == {
        "manifest.json",
        *(item["filename"] for item in artifacts),
    }
    assert all("token" not in json.dumps(item).lower() for item in artifacts)


def test_host_verifier_rejects_internal_incomplete_and_tampered_sets(tmp_path, monkeypatch):
    artifacts = _production_root(tmp_path)
    verifier = _load_verifier()
    _trust_release_attestations(verifier, monkeypatch)

    manifest_path = tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["channel"] = "internal"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="channel=production"):
        _verify_root(verifier, tmp_path)

    manifest["channel"] = "production"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / artifacts[0]["filename"]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum mismatch"):
        _verify_root(verifier, tmp_path)


def test_host_verifier_rejects_extra_files(tmp_path, monkeypatch):
    _production_root(tmp_path)
    verifier = _load_verifier()
    _trust_release_attestations(verifier, monkeypatch)
    (tmp_path / "unexpected.txt").write_text("must not be served", encoding="utf-8")

    with pytest.raises(ValueError, match="only the manifest and three installers"):
        _verify_root(verifier, tmp_path)


def test_manifest_signature_flags_cannot_replace_trusted_attestation(tmp_path, monkeypatch):
    _production_root(tmp_path)
    verifier = _load_verifier()

    def reject_untrusted_release(*_args, **_kwargs):
        raise ValueError("trusted release attestation could not be verified")

    monkeypatch.setattr(verifier, "_verify_attestation", reject_untrusted_release)
    with pytest.raises(ValueError, match="trusted release attestation"):
        _verify_root(verifier, tmp_path)


def test_attestation_verifier_rejects_forged_signature_predicate(tmp_path, monkeypatch):
    verifier = _load_verifier()
    artifact = tmp_path / "connector.exe"
    artifact.write_bytes(b"signed-subject")
    forged_response = [
        {
            "verificationResult": {
                "statement": {
                    "predicate": {
                        "platform": "windows",
                        "authenticode_verified": False,
                    }
                }
            }
        }
    ]
    captured_command = []

    def fake_run(command, **_kwargs):
        captured_command.extend(command)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(forged_response),
        )

    monkeypatch.setattr(verifier.subprocess, "run", fake_run)
    with pytest.raises(ValueError, match="predicate is invalid"):
        verifier._verify_attestation(
            artifact,
            expected_predicate={
                "platform": "windows",
                "authenticode_verified": True,
            },
        )
    assert (
        captured_command[captured_command.index("--repo") + 1]
        == "Moways3305/knowledge-asset-platform"
    )
    assert (
        captured_command[captured_command.index("--signer-workflow") + 1]
        == "Moways3305/knowledge-asset-platform/.github/workflows/"
        "workbuddy-connector-trusted-builder.yml"
    )
    assert (
        captured_command[captured_command.index("--cert-identity") + 1]
        == "https://github.com/Moways3305/knowledge-asset-platform/.github/"
        "workflows/workbuddy-connector-trusted-builder.yml@refs/heads/main"
    )
    assert captured_command[captured_command.index("--source-ref") + 1] == "refs/heads/main"
    assert "--deny-self-hosted-runners" in captured_command

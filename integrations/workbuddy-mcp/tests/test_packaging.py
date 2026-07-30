from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from connector_build import build_binary as binary_builder
from connector_build.create_manifest import create_manifest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


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


@pytest.mark.parametrize(
    ("system", "filename"),
    [("Windows", "kap-workbuddy-connector.exe"), ("Darwin", "kap-workbuddy-connector")],
)
def test_binary_builder_uses_absolute_platform_contract(monkeypatch, tmp_path, system, filename):
    output = tmp_path / "dist"
    work = tmp_path / "work"
    run = Mock()

    def create_binary(command, **kwargs):
        Path(command[command.index("--distpath") + 1], filename).write_bytes(b"binary")

    run.side_effect = create_binary
    monkeypatch.setattr(binary_builder.platform, "system", lambda: system)
    monkeypatch.setattr(binary_builder.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(binary_builder.subprocess, "run", run)

    binary = binary_builder.build_binary(output, work)

    command = run.call_args.args[0]
    assert Path(command[command.index("--distpath") + 1]).is_absolute()
    assert binary == output.resolve() / filename
    assert command[command.index("--collect-submodules") + 1] == "mcp.server"
    assert "--collect-all" not in command
    run.assert_called_once_with(
        command, cwd=Path(binary_builder.__file__).resolve().parents[1], check=True
    )


def test_binary_builder_rejects_missing_output(monkeypatch, tmp_path):
    monkeypatch.setattr(binary_builder.platform, "system", lambda: "Windows")
    monkeypatch.setattr(binary_builder.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(binary_builder.subprocess, "run", Mock())

    with pytest.raises(SystemExit, match="missing or empty connector binary for windows"):
        binary_builder.build_binary(tmp_path / "dist", tmp_path / "work")


def test_binary_builder_reports_subprocess_failure_without_command_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(binary_builder.platform, "system", lambda: "Windows")
    monkeypatch.setattr(binary_builder.platform, "machine", lambda: "AMD64")
    failure = subprocess.CalledProcessError(1, ["python", "private-path"])
    monkeypatch.setattr(binary_builder.subprocess, "run", Mock(side_effect=failure))

    with pytest.raises(SystemExit, match=r"^connector binary build failed for windows-native$"):
        binary_builder.build_binary(tmp_path / "dist", tmp_path / "work")


def test_windows_script_stops_before_inno_setup_when_binary_is_missing():
    script = (PACKAGE_ROOT / "connector_build/windows/build.ps1").read_text(encoding="utf-8")
    build_check = script.index("$LASTEXITCODE -ne 0")
    binary_check = script.index("Missing or empty connector binary for windows-x64")
    inno_call = script.index("& $iscc")

    assert build_check < binary_check < inno_call
    assert 'Join-Path $work "binary\\kap-workbuddy-connector.exe"' in script
    assert "$env:CONNECTOR_BINARY = $binary" in script
    assert "$signed = $false" in script
    assert "notarized = $false" in script


def test_windows_installer_preserves_custom_directory_and_stable_process_entry():
    installer = (PACKAGE_ROOT / "connector_build/windows/connector.iss").read_text(encoding="utf-8")
    assert "AppId={{38DBEB78-691E-4CFD-B81B-1896A06D2329}" in installer
    assert r"DefaultDirName={autopf}\KAP WorkBuddy Connector" in installer
    assert "UsePreviousAppDir=yes" in installer
    assert "DisableDirPage=yes" not in installer
    assert (
        'DestDir: "{app}"; DestName: "kap-workbuddy-connector.exe"; Flags: ignoreversion'
        in installer
    )


def test_macos_script_checks_each_installer_input():
    script = (PACKAGE_ROOT / "connector_build/macos/build.sh").read_text(encoding="utf-8")
    binary_check = script.index("Missing or empty connector binary for macos-$ARCH")
    copy_call = script.index('cp "$BINARY"')
    payload_check = script.index("Missing or empty app binary before payload copy")
    payload_copy = script.index('cp -R "$APP"')
    package_check = script.index("Missing or empty package input before pkgbuild")
    pkgbuild_call = script.index("pkgbuild --root")

    assert binary_check < copy_call < payload_check < payload_copy < package_check < pkgbuild_call
    assert "SIGNED=false" in script
    assert "NOTARIZED=false" in script


def test_macos_packages_reinstall_the_stable_app_executable_for_both_architectures():
    script = (PACKAGE_ROOT / "connector_build/macos/build.sh").read_text(encoding="utf-8")
    assert 'FILENAME="kap-workbuddy-connector-$VERSION-macos-$ARCH.pkg"' in script
    assert 'mkdir -p "$APP/Contents/MacOS" "$PAYLOAD/Applications"' in script
    assert 'cp "$BINARY" "$APP/Contents/MacOS/kap-workbuddy-connector"' in script
    assert 'cp -R "$APP" "$PAYLOAD/Applications/"' in script
    assert '--install-location "/" "$UNSIGNED"' in script


def test_internal_workflow_steps_do_not_reference_signing_secrets():
    workflow = (REPOSITORY_ROOT / ".github/workflows/workbuddy-connector-release.yml").read_text(
        encoding="utf-8"
    )
    windows_internal = workflow.split("- name: Build unsigned internal installer", 1)[1].split(
        "- name: Build installer and enforce production signing", 1
    )[0]
    macos_internal = workflow.split("- name: Build unsigned internal package", 1)[1].split(
        "- name: Build package and enforce Developer ID notarization", 1
    )[0]

    assert "secrets." not in windows_internal
    assert "secrets." not in macos_internal
    assert "fail-fast: false" in workflow

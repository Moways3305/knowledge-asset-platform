"""Release planning is read-only, failures stop before registration, and Git ranges are explicit."""

import importlib.util
import io
import json
import subprocess
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/deploy_release.py"
spec = importlib.util.spec_from_file_location("deploy_release_script", SCRIPT)
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)


@pytest.fixture
def repository(tmp_path, monkeypatch):
    monkeypatch.setattr(script, "ROOT", tmp_path)

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, encoding="utf-8").strip()

    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    git("config", "commit.gpgsign", "false")
    git("commit", "--allow-empty", "-qm", "baseline")
    base = git("rev-parse", "HEAD")
    git("commit", "--allow-empty", "-qm", "fix: internal sensitive subject must not be published")
    return tmp_path, base, git


def test_prepare_collects_only_new_fragments_and_never_publishes_raw_commit_subject(repository):
    root, base, git = repository
    fallback = script.prepare("1.2.0", base)
    assert "待审核补充" in fallback["entries"][0]["text"]
    assert "sensitive" not in json.dumps(fallback)
    folder = root / "release-notes"
    folder.mkdir()
    entries = [{"kind": "fixed", "text": "文件上传后可查看处理进度。"}]
    (folder / "upload.json").write_text(json.dumps(entries), encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "release note")
    before = git("status", "--porcelain")
    manifest = script.prepare("v1.2.0", base)
    assert manifest["entries"] == entries
    assert manifest["commit"] == git("rev-parse", "HEAD")
    assert manifest["previous_commit"] == base
    assert git("status", "--porcelain") == before == ""


@pytest.mark.parametrize("failed_step", [0, 1, 2, 3, 4, None])
def test_failed_build_migration_or_health_never_registers(monkeypatch, failed_step):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if failed_step == len(calls) - 1:
            raise subprocess.CalledProcessError(1, "deployment step")

    monkeypatch.setattr(script.subprocess, "run", run)
    monkeypatch.setattr(script, "git", lambda *args: "a" * 40 if args[0] == "rev-parse" else "")
    monkeypatch.setattr(script, "verify_baseline", lambda *args: None)
    args = SimpleNamespace(
        origin="https://kap.example.test",
        sync_only=False,
        backup_confirmed=True,
        bootstrap_baseline=False,
    )
    if failed_step is None:
        script.execute(args, {"version": "v1.2.0", "commit": "a" * 40})
        assert calls[-1][-3:] == ["app.commands.sync_release_notes", "--origin", args.origin]
    else:
        with pytest.raises(subprocess.CalledProcessError):
            script.execute(args, {"version": "v1.2.0", "commit": "a" * 40})
        assert all(
            "app.commands.sync_release_notes" not in call or "--check-only" in call
            for call in calls
        )


def test_apply_refuses_dirty_checkout_and_missing_backup(monkeypatch):
    monkeypatch.setattr(script, "git", lambda *args: " M modified.py")
    args = SimpleNamespace(
        origin="https://kap.example.test",
        sync_only=False,
        backup_confirmed=False,
        bootstrap_baseline=False,
    )
    with pytest.raises(ValueError, match="备份"):
        script.execute(args, {})
    args.backup_confirmed = True
    with pytest.raises(ValueError, match="不干净"):
        script.execute(args, {})


def test_same_commit_is_not_a_new_release(repository):
    _, _, git = repository
    with pytest.raises(ValueError, match="相同"):
        script.prepare("1.2.0", git("rev-parse", "HEAD"))


@pytest.mark.parametrize(
    "running,bootstrap,accepted",
    [
        ({"commit": "b" * 40}, False, True),
        ({"commit": "c" * 40}, True, False),
        (None, False, False),
        (None, True, True),
        (404, True, True),
        (404, False, False),
        (302, True, False),
        (503, True, False),
    ],
)
def test_baseline_bootstrap_only_accepts_missing_legacy_identity(
    monkeypatch, running, bootstrap, accepted
):
    class Opener:
        def open(self, *args, **kwargs):
            if isinstance(running, int):
                raise urllib.error.HTTPError(
                    "https://kap.example.test/health/release", running, "error", {}, None
                )
            return io.BytesIO(json.dumps(running).encode())

    monkeypatch.setattr(script.urllib.request, "build_opener", lambda *args: Opener())
    if accepted:
        script.verify_baseline("https://kap.example.test", {"previous_commit": "b" * 40}, bootstrap)
    else:
        with pytest.raises(ValueError):
            script.verify_baseline(
                "https://kap.example.test", {"previous_commit": "b" * 40}, bootstrap
            )


def test_sync_only_never_rebuilds_or_migrates(monkeypatch):
    calls = []
    monkeypatch.setattr(script.subprocess, "run", lambda cmd, **kwargs: calls.append(cmd))
    args = SimpleNamespace(origin="https://kap.example.test", sync_only=True)
    script.execute(args, {})
    assert len(calls) == 1 and "exec" in calls[0]

"""Release planning is read-only, failures stop before registration, and Git ranges are explicit."""

import importlib.util
import io
import json
import subprocess
import tarfile
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/deploy_release.py"
spec = importlib.util.spec_from_file_location("deploy_release_script", SCRIPT)
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)

image_spec = importlib.util.spec_from_file_location(
    "check_release_image", SCRIPT.with_name("check_release_image.py")
)
image_script = importlib.util.module_from_spec(image_spec)
image_spec.loader.exec_module(image_script)


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
        prefix = [
            "docker",
            "compose",
            "-p",
            "kap",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.prod.yml",
        ]
        assert all(call[: len(prefix)] == prefix for call in calls)
        assert calls[0][-6:] == ["migrate", "backend", "worker", "ocr_worker", "beat", "frontend"]
        assert calls[4][-5:] == ["backend", "worker", "ocr_worker", "beat", "frontend"]
        assert "--no-deps" in calls[4] and "--wait" in calls[4]
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
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "wrong-stack")
    calls = []
    monkeypatch.setattr(script.subprocess, "run", lambda cmd, **kwargs: calls.append(cmd))
    args = SimpleNamespace(origin="https://kap.example.test", sync_only=True)
    script.execute(args, {})
    assert len(calls) == 1 and "exec" in calls[0]
    assert calls[0][:4] == ["docker", "compose", "-p", "kap"]


@pytest.mark.parametrize("component", ["backend", "frontend"])
def test_restricted_image_context_does_not_change_sources_or_include_secrets(
    repository, monkeypatch, component
):
    root, _, git = repository
    monkeypatch.setattr(image_script, "ROOT", root)
    source = root / "backend/app/models/release_note.py"
    source.parent.mkdir(parents=True)
    source.write_text("# fixture", encoding="utf-8")
    (root / "backend/Dockerfile").write_text("FROM scratch", encoding="utf-8")
    (root / "Dockerfile.frontend").write_text("FROM scratch", encoding="utf-8")
    (root / "backend/.env").write_text("SECRET=never-archive", encoding="utf-8")
    (root / ".env.production").write_text("SECRET=never-archive", encoding="utf-8")
    git("add", ".")
    (root / "backend/local-backup.dump").write_text("private", encoding="utf-8")
    mode_before = source.stat().st_mode
    with image_script.restricted_context(component) as stream:
        with tarfile.open(fileobj=stream, mode="r") as archive:
            members = archive.getmembers()
            prefix = "" if component == "backend" else "backend/"
            copied = archive.getmember(prefix + "app/models/release_note.py")
            assert copied.mode == 0o600
            assert archive.getmember(prefix + "app/models").mode == 0o700
            assert all(member.mode == (0o700 if member.isdir() else 0o600) for member in members)
            assert all(
                ".env" not in member.name and "backup" not in member.name for member in members
            )
            assert archive.extractfile(copied).read() == b"# fixture"
    assert source.stat().st_mode == mode_before
    assert source.read_text(encoding="utf-8") == "# fixture"


def test_image_checker_exercises_nonroot_backend_and_nginx(monkeypatch):
    import base64
    import sys
    from contextlib import nullcontext

    calls = []
    manifest = {}

    def run(command, **kwargs):
        calls.append(command)
        if command[1] == "build":
            assert command[-1] == "-" and "stdin" in kwargs
            manifest.update(json.loads(base64.b64decode(command[3].split("=", 1)[1])))

    def output(command, **kwargs):
        calls.append(command)
        if "kap-backend-ci" in command:
            code = command[-1]
            assert "os.geteuid() != 0" in code and "import app.models" in code
            assert "import app.commands.sync_release_notes" in code
            assert "/app/alembic.ini" in code and "/app/alembic/versions" in code
            return json.dumps(manifest)
        return json.dumps({key: manifest[key] for key in ("version", "commit")})

    monkeypatch.setattr(
        image_script, "restricted_context", lambda component: nullcontext(io.BytesIO())
    )
    monkeypatch.setattr(image_script.subprocess, "run", run)
    monkeypatch.setattr(image_script.subprocess, "check_output", output)
    for component in ("backend", "frontend"):
        monkeypatch.setattr(sys, "argv", ["check_release_image.py", component])
        image_script.main()
    assert ["docker", "run", "--rm", "kap-frontend-ci", "nginx", "-t"] in calls
    assert all("--user" not in call for call in calls)

import subprocess
import sys
import tempfile
from pathlib import Path


def test_executable_architecture_boundaries():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "check_architecture.py")],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "service modules in recursive graph acyclic" in result.stdout
    assert "API modules scanned" in result.stdout
    assert "5 governed APIs command-free" in result.stdout
    assert "6 bounded legacy API baselines" in result.stdout
    assert "3 service facades ORM-free and size-bounded" in result.stdout
    assert "upload orchestrator size-bounded" in result.stdout
    assert "all service notification imports and record writes use Outbox" in result.stdout
    checker = (root / "scripts" / "check_architecture.py").read_text(encoding="utf-8")
    assert '"agent_gateway.py"' in checker
    assert '"my_knowledge"' in checker


def test_architecture_checker_detects_direct_api_session_write():
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    try:
        from scripts.check_architecture import _api_session_writes
    finally:
        sys.path.pop(0)

    with tempfile.TemporaryDirectory() as directory:
        fixture = Path(directory) / "agent_gateway.py"
        fixture.write_text(
            "async def endpoint(session):\n    await session.commit()\n",
            encoding="utf-8",
        )
        assert _api_session_writes(fixture) == [(2, "commit")]


def test_architecture_checker_sees_notification_bypass_in_inline_import():
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    try:
        from scripts.check_architecture import _service_imports
    finally:
        sys.path.pop(0)

    with tempfile.TemporaryDirectory() as directory:
        fixture = Path(directory) / "my_knowledge.py"
        fixture.write_text(
            "def command():\n    from app.services.notifications import notify_review_pending\n",
            encoding="utf-8",
        )
        assert "notifications" in _service_imports(fixture)


def test_architecture_checker_includes_nested_modules_and_cycles():
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    try:
        from scripts.check_architecture import _cycles, _service_graph
    finally:
        sys.path.pop(0)

    with tempfile.TemporaryDirectory() as directory:
        services = Path(directory)
        jobs = services / "jobs"
        workflows = services / "workflows"
        jobs.mkdir()
        workflows.mkdir()
        (jobs / "runner.py").write_text(
            "from app.services.workflows.approval import approve\n",
            encoding="utf-8",
        )
        (workflows / "approval.py").write_text(
            "from app.services.jobs.runner import run\n",
            encoding="utf-8",
        )

        graph = _service_graph(services)

        assert graph == {
            "jobs.runner": {"workflows.approval"},
            "workflows.approval": {"jobs.runner"},
        }
        assert _cycles(graph) == [["jobs.runner", "workflows.approval", "jobs.runner"]]


def test_architecture_checker_detects_direct_notification_record_write():
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    try:
        from scripts.check_architecture import _direct_notification_writes
    finally:
        sys.path.pop(0)

    with tempfile.TemporaryDirectory() as directory:
        fixture = Path(directory) / "ops_alerts.py"
        fixture.write_text(
            "async def emit(session):\n"
            "    await alert_service.record_local_notification(session)\n",
            encoding="utf-8",
        )
        assert _direct_notification_writes(fixture) == [(2, "record_local_notification")]

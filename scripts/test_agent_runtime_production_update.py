"""Verify PR #245 delivery guards and its launcher without production access."""

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import deploy_agent_runtime_update as release
from production_cutover_runtime import Runtime
import test_maintenance_production_update as fixtures


class AgentRuntimeDelivery(unittest.TestCase):
    def setUp(self):
        guard = patch.dict(release.delivery.__dict__)
        guard.start()
        self.addCleanup(guard.stop)
        self.fixture = fixtures.MaintenanceDelivery()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        release.configure()
        self.stage = release.stage
        self.fixture.old["kap-frontend-1"]["Config"].update(
            Cmd=["nginx", "-g", "daemon off;"],
            Entrypoint=["/docker-entrypoint.sh"],
            StopSignal="SIGQUIT",
        )
        self.set_baseline(next(iter(release.BASELINES)))
        self.fixture.sql_mock.side_effect = self.sql

    def set_baseline(self, revision):
        f = self.fixture
        f.baseline = revision
        self.record = {
            "revision": revision,
            "version": release.BASELINES[revision][0],
            "managed_compose_file": str(f.managed),
            "record_directory": str(f.prior),
        }
        f.save(f.root / "current-release.json", self.record)
        f.save(
            f.prior / "report.json",
            {
                **self.record,
                "passed": True,
                "checkpoint": "complete",
                "production_switched": True,
                "post_deployment_tasks_pending": [],
            },
        )

    def sql(self, runner, item, query):
        if query == "SELECT version_num FROM alembic_version;":
            return release.BASELINES[self.fixture.baseline][1]
        if "pg_tablespace" in query:
            return "0"
        raise AssertionError("Unexpected SQL operation")

    def test_both_managed_baselines_capture_and_pin_the_merged_runtime_release(self):
        f = self.fixture
        expected = {
            "57cd2720d6e2cef035adc6368846f7888bbfafa1": "v1.6.0",
            "f9d4cdbf220e65255b88513bb16fffd9f8d36c1f": "v1.6.1",
        }
        self.assertEqual({key: value[0] for key, value in release.BASELINES.items()}, expected)
        for index, (revision, version) in enumerate(expected.items()):
            with self.subTest(version=version):
                self.set_baseline(revision)
                inventory = f.root / f"inventory-agent-runtime-{index}"
                inventory.mkdir()
                f.health.reset_mock()
                self.assertEqual(self.stage.validate_inventory(f.runner, inventory), f.old)
                self.assertEqual(self.stage.BASELINE, revision)
                self.assertEqual(self.stage.BASELINE_VERSION, version)
                self.assertEqual(self.stage.BASELINE_SCHEMA, "0096_ai_workspace")
                self.assertEqual(self.stage.REVISION, "41e68da55b8f353d3ec55821ecfe815557ff6641")
                self.assertEqual(self.stage.VERSION, "v1.7.0")
                self.assertEqual(self.stage.SCHEMA, "0098_legacy_agent_sessions")
                self.assertIs(self.stage.table_snapshot, release.migration_check.table_snapshot)
                f.health.assert_called_once_with(
                    f.runner, f.old["kap-backend-1"]["Id"], revision, version
                )
                captured = json.loads((inventory / "report.json").read_text())
                self.assertEqual(captured["migration"], "0096_ai_workspace")
                entries = self.stage.RELEASE_ENTRIES
                for entry in release.navigation.ENTRIES:
                    self.assertEqual(entry in entries, version == "v1.6.0")
        f.runner.execute.assert_not_called()

    def test_unknown_wrong_version_and_already_deployed_stop_before_runtime_access(self):
        f = self.fixture
        cases = [("f" * 40, "v1.6.1", "unsupported_baseline")]
        cases += [(revision, "v1.5.0", "unsupported_baseline") for revision in release.BASELINES]
        cases.append((release.REVISION, release.VERSION, "release_already_deployed"))
        for revision, version, error in cases:
            f.save(
                f.root / "current-release.json",
                {**self.record, "revision": revision, "version": version},
            )
            with self.subTest(revision=revision), self.assertRaisesRegex(RuntimeError, error):
                self.stage.validate_inventory(f.runner, f.inventory)
            f.runner.inspect.assert_not_called()
            f.runner.execute.assert_not_called()

    def test_image_environment_health_or_managed_reference_drift_prevents_build(self):
        f = self.fixture
        original = copy.deepcopy(f.old["kap-backend-1"])
        for parent, key, value, error in (
            (None, "Image", "unexpected", "managed_image_changed"),
            ("Config", "Env", ["MODEL_KEY=changed"], "managed_environment_changed"),
            ("State", "Running", False, "baseline_service_not_healthy"),
            (
                "Config",
                "Labels",
                {"com.docker.compose.project.config_files": "/changed/compose.json"},
                "runtime_compose_reference_changed",
            ),
        ):
            target = f.old["kap-backend-1"]
            (target if parent is None else target[parent])[key] = value
            with self.subTest(error=error), self.assertRaisesRegex(RuntimeError, error):
                self.stage.validate_inventory(f.runner, f.inventory)
            f.old["kap-backend-1"] = copy.deepcopy(original)
        f.runner.execute.assert_not_called()

    def test_incomplete_previous_release_prevents_build(self):
        f = self.fixture
        previous = json.loads((f.prior / "report.json").read_text())
        for change in (
            {"passed": False},
            {"checkpoint": "opening_traffic"},
            {"production_switched": False},
            {"manual_recovery_required": True},
            {"post_deployment_tasks_pending": ["cleanup"]},
            {"revision": "f" * 40},
        ):
            f.save(f.prior / "report.json", {**previous, **change})
            with (
                self.subTest(change=change),
                self.assertRaisesRegex(RuntimeError, "previous_release_incomplete"),
            ):
                self.stage.validate_inventory(f.runner, f.inventory)
        f.runner.execute.assert_not_called()

    def test_wrong_schema_is_rejected_before_build(self):
        f = self.fixture
        f.sql_mock.side_effect = lambda *args: "0095_knowledge_tasks"
        with self.assertRaisesRegex(RuntimeError, "unexpected_inventory"):
            self.stage.validate_inventory(f.runner, f.inventory)
        f.runner.execute.assert_not_called()

    def test_schema_change_after_inventory_capture_is_rejected_before_build(self):
        f = self.fixture
        schema_calls = 0

        def changed(runner, item, query):
            nonlocal schema_calls
            if query == "SELECT version_num FROM alembic_version;":
                schema_calls += 1
                return "0096_ai_workspace" if schema_calls == 1 else release.SCHEMA
            return self.sql(runner, item, query)

        f.sql_mock.side_effect = changed
        with self.assertRaisesRegex(RuntimeError, "schema_changed"):
            self.stage.validate_inventory(f.runner, f.inventory)
        f.runner.execute.assert_not_called()

    def test_success_report_requires_verified_business_data_and_reports_schema_change(self):
        for revision in release.BASELINES:
            with self.subTest(revision=revision):
                self.set_baseline(revision)
                release.select_profile(self.record)
                result = {}

                def completed(_runner, _inventory, _out, report, _holder):
                    report.update(passed=True, business_data_preserved=True)

                with patch.object(release.delivery, "_execute", side_effect=completed):
                    self.stage.execute(None, None, None, result, [])
                self.assertIs(result["database_schema_changed"], True)
                self.assertIs(result["existing_agent_configuration_preserved"], True)
                self.assertEqual(result["previous_revision"], revision)
                self.assertEqual(result["previous_version"], release.BASELINES[revision][0])
        with (
            patch.object(release.delivery, "_execute"),
            self.assertRaisesRegex(RuntimeError, "existing_data_verification_missing"),
        ):
            self.stage.execute(None, None, None, {}, [])

    def test_recovery_uses_saved_profile_and_only_the_fixed_target(self):
        f = self.fixture
        for revision in release.BASELINES:
            self.set_baseline(revision)
            f.save(f.inventory / "current-release-before.json", self.record)
            manifest = {
                "commit": release.REVISION,
                "version": release.VERSION,
                "previous_commit": revision,
            }
            f.save(f.out / "release-manifest.json", manifest)
            f.save(
                f.root / "current-release.json",
                {"revision": release.REVISION, "version": release.VERSION},
            )
            with patch.object(release.delivery, "_recover_record") as recover:
                self.stage.recover_record(f.runner, f.inventory, f.out)
                recover.assert_called_once_with(f.runner, f.inventory, f.out)
                self.assertEqual(self.stage.BASELINE, revision)
                self.assertEqual(self.stage.SCHEMA, "0098_legacy_agent_sessions")
                for change in (
                    {"commit": revision},
                    {"version": "v1.6.1"},
                    {"previous_commit": "a" * 40},
                ):
                    f.save(f.out / "release-manifest.json", {**manifest, **change})
                    recover.reset_mock()
                    with (
                        self.subTest(revision=revision, change=change),
                        self.assertRaisesRegex(RuntimeError, "recovery_release_mismatch"),
                    ):
                        self.stage.recover_record(f.runner, f.inventory, f.out)
                    recover.assert_not_called()

    def test_frontend_stop_fix_is_used_for_original_and_owned_candidate(self):
        runtime = object.__new__(release.AgentRuntime)
        runtime.r = Mock()
        runtime.token = "release-synthetic0"
        original = self.fixture.old["kap-frontend-1"]
        candidate = {**original, "Id": "new-frontend"}
        runtime.state = {
            "originals": {"kap-frontend-1": original},
            "new": {"kap-frontend-1": candidate["Id"]},
        }
        runtime.owned = Mock(return_value=candidate)
        with patch.object(release.navigation, "stop_frontend") as stop:
            runtime.stop("kap-frontend-1", original["Id"])
            stop.assert_called_once_with(runtime.r, original, token=None)
            stop.reset_mock()
            runtime.stop("kap-frontend-1", candidate["Id"])
            runtime.owned.assert_called_once_with(candidate["Id"])
            stop.assert_called_once_with(runtime.r, candidate, token=runtime.token)
            stop.reset_mock()
            with self.assertRaisesRegex(RuntimeError, "unexpected_frontend_identity"):
                runtime.stop("kap-frontend-1", "unowned")
            stop.assert_not_called()
        with patch.object(Runtime, "stop", autospec=True) as stop:
            runtime.stop("kap-worker-1", "worker-id", grace=90)
            stop.assert_called_once_with(runtime, "kap-worker-1", "worker-id", grace=90)

    def migration_runtime(self):
        runtime = object.__new__(release.AgentRuntime)
        runtime.directory = self.fixture.out
        runtime.helper_image = "sha256:" + "a" * 64
        self.fixture.save(runtime.directory / "database-before-private.json", {"synthetic": True})
        return runtime

    def test_migration_success_is_followed_by_candidate_readonly_verification(self):
        runtime = self.migration_runtime()
        command = ["python", "-m", "alembic", "upgrade", "head"]
        env = ("DATABASE_URL=synthetic-only", "GENERATION_MODEL_ENCRYPTION_KEY=fixture")
        with (
            patch.object(Runtime, "helper", autospec=True) as helper,
            patch.object(release.migration_check, "redaction_check_code", return_value="safe-code"),
        ):
            runtime.helper(command, image=runtime.helper_image, network="kap_internal", env=env)
        self.assertEqual(helper.call_count, 2)
        migrated, verified = helper.call_args_list
        self.assertEqual(migrated.args, (runtime, command, ()))
        self.assertEqual(verified.args, (runtime, ["python", "-c", "safe-code"]))
        for call in (migrated, verified):
            self.assertEqual(call.kwargs["image"], runtime.helper_image)
            self.assertEqual(call.kwargs["network"], "kap_internal")
            self.assertEqual(call.kwargs["env"], env)
        snapshot = runtime.directory / "database-before-private.json"
        self.assertEqual(
            verified.kwargs["mounts"],
            (
                f"type=bind,src={snapshot},dst=/migration-check/database-before-private.json,readonly",
            ),
        )

    def test_migration_or_verification_failure_propagates_without_faking_success(self):
        runtime = self.migration_runtime()
        command = ["python", "-m", "alembic", "upgrade", "head"]
        for failing_call, message in ((1, "migration_failed"), (2, "redaction_failed")):
            effects = [None] * (failing_call - 1) + [RuntimeError(message)]
            with (
                self.subTest(failing_call=failing_call),
                patch.object(Runtime, "helper", autospec=True, side_effect=effects) as helper,
                patch.object(
                    release.migration_check, "redaction_check_code", return_value="safe-code"
                ) as check,
                self.assertRaisesRegex(RuntimeError, message),
            ):
                runtime.helper(command, image=runtime.helper_image, network="kap_internal")
            self.assertEqual(helper.call_count, failing_call)
            self.assertEqual(check.call_count, failing_call - 1)

    def test_migration_rejects_wrong_image_network_or_absent_snapshot_before_running(self):
        runtime = self.migration_runtime()
        command = ["python", "-m", "alembic", "upgrade", "head"]
        for image, network in (("different-image", "kap_internal"), (runtime.helper_image, "none")):
            with (
                self.subTest(image=image, network=network),
                patch.object(Runtime, "helper", autospec=True) as helper,
                self.assertRaisesRegex(RuntimeError, "unexpected_migration_runtime"),
            ):
                runtime.helper(command, image=image, network=network)
            helper.assert_not_called()
        snapshot = runtime.directory / "database-before-private.json"
        snapshot.unlink()
        with (
            patch.object(Runtime, "helper", autospec=True) as helper,
            self.assertRaisesRegex(RuntimeError, "migration_snapshot_missing"),
        ):
            runtime.helper(command, image=runtime.helper_image, network="kap_internal")
        helper.assert_not_called()

    def test_non_migration_helper_does_not_trigger_legacy_verification(self):
        runtime = self.migration_runtime()
        command = ["python", "-c", "print('synthetic readiness probe')"]
        with (
            patch.object(Runtime, "helper", autospec=True) as helper,
            patch.object(release.migration_check, "redaction_check_code") as check,
        ):
            runtime.helper(command)
        helper.assert_called_once_with(runtime, command, (), image=None, network="none", env=())
        check.assert_not_called()


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "requires local Bash")
class AgentRuntimeLauncher(unittest.TestCase):
    def run_launcher(self, lock_result):
        with tempfile.TemporaryDirectory(prefix="kap-launcher-test-") as directory:
            root = Path(directory)
            bin_path = root / "bin"
            bin_path.mkdir()
            home = root / "home"
            home.mkdir()
            helper_dir = root / "helper"
            helper_dir.mkdir()
            script = helper_dir / "launch_agent_runtime_update.sh"
            script.write_text(Path(__file__).with_name(script.name).read_text(), encoding="utf-8")
            helper = helper_dir / "deploy_agent_runtime_update.py"
            helper.write_text(
                "import json, os, pathlib, sys\n"
                "pathlib.Path(os.environ['KAP_FIXTURE_ROOT'], 'helper-called.json').write_text("
                "json.dumps(sys.argv))\nprint('synthetic helper completed')\n",
                encoding="utf-8",
            )
            # Fail closed on every unrecognised command. No real sudo, Git,
            # production path, Docker or database operation can be reached.
            shim = r"""#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys, tempfile
root = pathlib.Path(os.environ["KAP_FIXTURE_ROOT"]).resolve()
name, args = pathlib.Path(sys.argv[0]).name, sys.argv[1:]
def safe_path(value):
    path = pathlib.Path(value).resolve()
    assert path.is_relative_to(root), "path outside synthetic fixture"
    return path
with (root / "commands.jsonl").open("a") as stream:
    stream.write(json.dumps([name, *args]) + "\n")
if name == "id":
    assert args == ["-un"]
    print("ubuntu")
elif name == "git":
    assert args[:4] == ["-C", "/data/kap/repo", "cat-file", "-e"]
    assert args[4] == "41e68da55b8f353d3ec55821ecfe815557ff6641^{commit}"
elif name == "mktemp":
    assert args[0] == "-d"
    pattern = pathlib.Path(args[1])
    assert pattern.parent == pathlib.Path("/data/kap/release-preparations") or pattern.parent == root / "home"
    print(tempfile.mkdtemp(prefix=pattern.name.rstrip("X"), dir=root))
elif name == "sudo":
    if args == ["-v"]:
        sys.exit(0)
    assert args.pop(0) == "-n"
    command = args.pop(0)
    if command == "mktemp":
        sys.exit(subprocess.run([str(root / "bin" / "mktemp"), *args]).returncode)
    elif command == "tee":
        assert len(args) == 1
        safe_path(args[0]).write_text(sys.stdin.read())
    elif command == "chmod":
        assert args[0] == "600" and len(args) == 2
        safe_path(args[1]).chmod(0o600)
    elif command == "flock":
        assert args[:4] == ["-n", "-E", "75", "/data/kap/repo/.git/kap-deploy.lock"]
        assert args[4:9] == ["env", "GIT_OPTIONAL_LOCKS=0", "python3", "-B", "-u"]
        if os.environ["KAP_FIXTURE_LOCK_RESULT"] == "75":
            sys.exit(75)
        safe_path(args[9])
        assert args[10] == "--inventory" and args[12] == "--output"
        safe_path(args[11]); safe_path(args[13])
        sys.exit(subprocess.run(args[4:]).returncode)
    else:
        raise AssertionError("unapproved sudo command")
else:
    raise AssertionError("unapproved executable")
"""
            for name in ("id", "git", "mktemp", "sudo"):
                target = bin_path / name
                target.write_text(shim, encoding="utf-8")
                target.chmod(0o700)
            env = {
                **os.environ,
                "HOME": str(home),
                "PATH": str(bin_path) + os.pathsep + os.environ["PATH"],
                "KAP_FIXTURE_ROOT": str(root),
                "KAP_FIXTURE_LOCK_RESULT": str(lock_result),
            }
            result = subprocess.run(
                ["bash", str(script)], env=env, capture_output=True, text=True, timeout=10
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            launches = list(root.glob("kap-agent-runtime-launch-*"))
            self.assertEqual(len(launches), 1)
            launch = launches[0]
            exit_path = launch / "exit-code"
            deadline = time.monotonic() + 5
            while not exit_path.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(exit_path.is_file(), (launch / "progress.log").read_text())
            self.assertEqual(exit_path.read_text().strip(), str(lock_result))
            self.assertEqual((launch / "helper-path.txt").read_text().strip(), str(helper))
            record = Path((launch / "record-path.txt").read_text().strip())
            inventory = Path((record / "inventory-path.txt").read_text().strip())
            self.assertTrue(record.name.startswith("release-"))
            self.assertTrue(inventory.name.startswith("inventory-agent-runtime-"))
            self.assertNotEqual(record, inventory)
            self.assertEqual((record / "inventory-path.txt").stat().st_mode & 0o777, 0o600)
            self.assertEqual((launch / "progress.log").stat().st_mode & 0o777, 0o600)
            self.assertIn(str(launch / "progress.log"), result.stdout)
            self.assertIn("tail --pid=", result.stdout)
            calls = [
                json.loads(line) for line in (root / "commands.jsonl").read_text().splitlines()
            ]
            self.assertEqual(sum(call[0] == "git" for call in calls), 1)
            self.assertEqual(sum(call[:3] == ["sudo", "-n", "flock"] for call in calls), 1)
            helper_called = root / "helper-called.json"
            if lock_result:
                self.assertFalse(helper_called.exists())
            else:
                self.assertEqual(
                    json.loads(helper_called.read_text()),
                    [str(helper), "--inventory", str(inventory), "--output", str(record)],
                )
                self.assertIn("synthetic helper completed", (launch / "progress.log").read_text())

    def test_background_launcher_pins_helper_and_preserves_private_progress_records(self):
        self.run_launcher(0)

    def test_busy_deployment_lock_keeps_exit_75_without_invoking_helper(self):
        self.run_launcher(75)


if __name__ == "__main__":
    unittest.main()

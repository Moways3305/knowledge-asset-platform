"""Check PR #246 delivery against a used v1.7.0 workspace, without production."""

import copy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import agent_runtime_migration_check as one_time_migration
import deploy_composer_agent_update as release
from production_cutover_runtime import Runtime
import test_maintenance_production_update as fixtures


class ComposerAgentDelivery(unittest.TestCase):
    def setUp(self):
        self.navigation = release.navigation
        self.delivery = self.navigation.delivery
        for module in (self.navigation, self.delivery):
            guard = patch.dict(module.__dict__)
            guard.start()
            self.addCleanup(guard.stop)
        self.fixture = fixtures.MaintenanceDelivery()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        release.configure()
        self.stage = self.navigation.stage
        f = self.fixture
        f.old["kap-frontend-1"]["Config"].update(
            Cmd=["nginx", "-g", "daemon off;"],
            Entrypoint=["/docker-entrypoint.sh"],
            StopSignal="SIGQUIT",
        )
        f.baseline = release.BASELINE
        self.record = {
            "revision": release.BASELINE,
            "version": release.BASELINE_VERSION,
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
        f.sql_mock.side_effect = self.sql

    def sql(self, runner, item, query):
        if query == "SELECT version_num FROM alembic_version;":
            return release.SCHEMA
        if "pg_tablespace" in query:
            return "0"
        raise AssertionError("Unexpected SQL operation")

    def test_exact_completed_baseline_and_target_release_are_pinned(self):
        f = self.fixture
        self.assertEqual(self.stage.validate_inventory(f.runner, f.inventory), f.old)
        self.assertEqual(self.stage.REVISION, "3caca683a38886ba491edf9352eb6499514bcad8")
        self.assertEqual(self.stage.VERSION, "v1.7.1")
        self.assertEqual(self.stage.BASELINE, "41e68da55b8f353d3ec55821ecfe815557ff6641")
        self.assertEqual(self.stage.BASELINE_VERSION, "v1.7.0")
        self.assertEqual(self.stage.SCHEMA, "0098_legacy_agent_sessions")
        self.assertEqual(self.stage.BASELINE_SCHEMA, self.stage.SCHEMA)
        self.assertEqual(len(self.stage.RELEASE_ENTRIES), 2)
        f.health.assert_called_once_with(
            f.runner, f.old["kap-backend-1"]["Id"], release.BASELINE, "v1.7.0"
        )
        f.runner.execute.assert_not_called()

    def test_older_unknown_wrong_version_and_duplicate_releases_are_rejected(self):
        f = self.fixture
        for revision, version, error in (
            ("57cd2720d6e2cef035adc6368846f7888bbfafa1", "v1.6.0", "unsupported_baseline"),
            ("f9d4cdbf220e65255b88513bb16fffd9f8d36c1f", "v1.6.1", "unsupported_baseline"),
            ("f" * 40, release.BASELINE_VERSION, "unsupported_baseline"),
            (release.BASELINE, "v1.6.1", "unsupported_baseline"),
            (release.REVISION, release.VERSION, "release_already_deployed"),
        ):
            f.save(
                f.root / "current-release.json",
                {**self.record, "revision": revision, "version": version},
            )
            with self.subTest(error=error), self.assertRaisesRegex(RuntimeError, error):
                self.stage.validate_inventory(f.runner, f.inventory)
            f.runner.inspect.assert_not_called()
            f.runner.execute.assert_not_called()

    def test_incomplete_previous_release_is_not_treated_as_a_baseline(self):
        f = self.fixture
        previous = json.loads((f.prior / "report.json").read_text())
        for change in (
            {"passed": False},
            {"checkpoint": "opening_traffic"},
            {"production_switched": False},
            {"manual_recovery_required": True},
            {"post_deployment_tasks_pending": ["cleanup"]},
        ):
            f.save(f.prior / "report.json", {**previous, **change})
            with (
                self.subTest(change=change),
                self.assertRaisesRegex(RuntimeError, "previous_release_incomplete"),
            ):
                self.stage.validate_inventory(f.runner, f.inventory)
        f.runner.execute.assert_not_called()

    def test_managed_environment_image_and_health_drift_prevent_build(self):
        f = self.fixture
        original = copy.deepcopy(f.old["kap-backend-1"])
        for parent, key, value, error in (
            (None, "Image", "unexpected", "managed_image_changed"),
            ("Config", "Env", ["MODEL_KEY=changed"], "managed_environment_changed"),
            ("State", "Running", False, "baseline_service_not_healthy"),
        ):
            target = f.old["kap-backend-1"]
            (target if parent is None else target[parent])[key] = value
            with self.subTest(error=error), self.assertRaisesRegex(RuntimeError, error):
                self.stage.validate_inventory(f.runner, f.inventory)
            f.old["kap-backend-1"] = copy.deepcopy(original)
        f.runner.execute.assert_not_called()

    def test_wrong_live_schema_prevents_build(self):
        f = self.fixture
        f.sql_mock.side_effect = lambda *args: "0096_ai_workspace"
        with self.assertRaisesRegex(RuntimeError, "unexpected_inventory"):
            self.stage.validate_inventory(f.runner, f.inventory)
        f.runner.execute.assert_not_called()

    def test_full_hash_covers_used_workspace_actions_and_all_original_tables(self):
        cutover = self.navigation.cutover
        self.assertIs(self.stage.table_snapshot, cutover.table_snapshot)
        tables = [
            "ai_workspace_actions",
            "ai_workspace_runs",
            "ai_workspace_messages",
            "ai_workspace_artifacts",
            "content_generation_models",
            "knowledge_agent_tasks",
        ]
        digests = [f"{index + 1}|existing-{name}" for index, name in enumerate(tables)]
        with (
            patch.object(one_time_migration, "validate_imports") as migration_proof,
            patch.object(
                cutover,
                "sql",
                side_effect=[json.dumps(tables), *['["id", "content"]'] * len(tables), *digests],
            ),
        ):
            columns, before = self.stage.table_snapshot(None, None)
        self.assertEqual(set(columns), set(tables))
        migration_proof.assert_not_called()
        with patch.object(cutover, "sql", side_effect=digests) as query:
            self.assertEqual(self.stage.table_snapshot(None, None, columns)[1], before)
            self.assertEqual(query.call_count, len(tables))
            self.assertFalse(any("NOT IN" in call.args[2] for call in query.call_args_list))
        for index, table in enumerate(tables):
            changed = list(digests)
            changed[index] = "0|deleted-or-modified"
            with self.subTest(table=table), patch.object(cutover, "sql", side_effect=changed):
                self.assertNotEqual(self.stage.table_snapshot(None, None, columns)[1], before)

    def test_runtime_keeps_bounded_shutdown_without_replaying_migration_proof(self):
        self.assertIs(self.stage.StageRuntime, self.navigation.NavigationRuntime)
        runtime = object.__new__(self.stage.StageRuntime)
        command = ["python", "-m", "alembic", "upgrade", "head"]
        with (
            patch.object(Runtime, "helper") as helper,
            patch.object(one_time_migration, "redaction_check_code") as proof,
        ):
            runtime.helper(command, image="candidate", network="kap_internal", env=("A=B",))
        helper.assert_called_once_with(
            command, image="candidate", network="kap_internal", env=("A=B",)
        )
        proof.assert_not_called()
        runtime.r = Mock()
        frontend = self.fixture.old["kap-frontend-1"]
        runtime.state = {"originals": {"kap-frontend-1": frontend}}
        with patch.object(self.navigation, "stop_frontend") as stop:
            runtime.stop("kap-frontend-1", frontend["Id"], grace=600)
        stop.assert_called_once_with(runtime.r, frontend, token=None)
        runtime.r.docker.assert_not_called()

    def test_recovery_requires_saved_baseline_and_exact_target_manifest(self):
        f = self.fixture
        f.save(f.inventory / "current-release-before.json", self.record)
        manifest = {
            "commit": release.REVISION,
            "version": release.VERSION,
            "previous_commit": release.BASELINE,
        }
        f.save(f.out / "release-manifest.json", manifest)
        with patch.object(self.delivery, "_recover_record") as recover:
            self.stage.recover_record(f.runner, f.inventory, f.out)
            recover.assert_called_once_with(f.runner, f.inventory, f.out)
            for change in (
                {"commit": release.BASELINE},
                {"version": "v1.7.0"},
                {"previous_commit": "a" * 40},
            ):
                f.save(f.out / "release-manifest.json", {**manifest, **change})
                recover.reset_mock()
                with (
                    self.subTest(change=change),
                    self.assertRaisesRegex(RuntimeError, "recovery_release_mismatch"),
                ):
                    self.stage.recover_record(f.runner, f.inventory, f.out)
                recover.assert_not_called()

    def test_success_report_requires_verified_data_and_reports_unchanged_schema(self):
        self.navigation.select_profile(self.record)
        report = {}

        def completed(_runner, _inventory, _out, result, _holder):
            result.update(passed=True, business_data_preserved=True)

        with patch.object(self.delivery, "_execute", side_effect=completed):
            self.stage.execute(None, None, None, report, [])
        self.assertIs(report["database_schema_changed"], False)
        self.assertIs(report["existing_agent_configuration_preserved"], True)
        self.assertEqual(report["previous_revision"], release.BASELINE)
        self.assertEqual(report["previous_version"], "v1.7.0")
        with (
            patch.object(self.delivery, "_execute"),
            self.assertRaisesRegex(RuntimeError, "existing_data_verification_missing"),
        ):
            self.stage.execute(None, None, None, {}, [])

    def test_launcher_keeps_the_previously_tested_lock_and_background_protocol(self):
        root = Path(__file__).resolve().parent
        previous = (root / "launch_agent_runtime_update.sh").read_text(encoding="utf-8")
        expected = (
            previous.replace("#245", "#246")
            .replace("deploy_agent_runtime_update.py", "deploy_composer_agent_update.py")
            .replace(release.BASELINE, release.REVISION)
            .replace("agent-runtime", "composer")
        )
        actual = (root / "launch_composer_agent_update.sh").read_text(encoding="utf-8")
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()

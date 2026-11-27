"""Validate the pinned same-schema navigation rollout without production access."""

import copy
import json
import unittest
from unittest.mock import Mock, patch

import deploy_navigation_update as release
import finalize_stage_release as finish
import test_maintenance_production_update as fixtures
from production_cutover_runtime import LABEL


class NavigationDelivery(unittest.TestCase):
    def setUp(self):
        guard = patch.dict(release.delivery.__dict__)
        guard.start()
        self.addCleanup(guard.stop)
        self.fixture = fixtures.MaintenanceDelivery()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        release.configure()
        self.stage = release.stage
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
            return release.BASELINE_SCHEMA
        if "pg_tablespace" in query:
            return "0"
        raise AssertionError("Unexpected SQL operation")

    def test_capture_pins_exact_merged_release_and_unchanged_schema(self):
        f = self.fixture
        self.assertEqual(self.stage.validate_inventory(f.runner, f.inventory), f.old)
        self.assertEqual(self.stage.REVISION, "f9d4cdbf220e65255b88513bb16fffd9f8d36c1f")
        self.assertEqual(self.stage.VERSION, "v1.6.1")
        self.assertEqual(self.stage.BASELINE, "57cd2720d6e2cef035adc6368846f7888bbfafa1")
        self.assertEqual(self.stage.BASELINE_VERSION, "v1.6.0")
        self.assertEqual(self.stage.SCHEMA, "0096_ai_workspace")
        self.assertEqual(self.stage.BASELINE_SCHEMA, self.stage.SCHEMA)
        self.assertIs(self.stage.table_snapshot, release.cutover.table_snapshot)
        f.health.assert_called_once_with(
            f.runner, f.old["kap-backend-1"]["Id"], release.BASELINE, "v1.6.0"
        )
        f.runner.execute.assert_not_called()

    def test_unknown_wrong_version_and_duplicate_stop_before_runtime_access(self):
        f = self.fixture
        for revision, version, error in (
            ("f" * 40, release.BASELINE_VERSION, "unsupported_baseline"),
            (release.BASELINE, "v1.5.0", "unsupported_baseline"),
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

    def test_managed_drift_or_incomplete_previous_release_stops_before_build(self):
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
        previous = json.loads((f.prior / "report.json").read_text())
        for change in (
            {"passed": False},
            {"checkpoint": "opening_traffic"},
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

    def test_older_live_schema_stops_before_build(self):
        f = self.fixture
        f.sql_mock.side_effect = lambda *args: "0095_knowledge_tasks"
        with self.assertRaisesRegex(RuntimeError, "unexpected_inventory"):
            self.stage.validate_inventory(f.runner, f.inventory)
        f.runner.execute.assert_not_called()

    def test_report_accurately_describes_same_schema_and_requires_data_verification(self):
        release.select_profile(self.record)
        report = {}

        def completed(_runner, _inventory, _out, result, _holder):
            result.update(passed=True, business_data_preserved=True)

        with patch.object(release.delivery, "_execute", side_effect=completed):
            self.stage.execute(None, None, None, report, [])
        self.assertIs(report["database_schema_changed"], False)
        self.assertIs(report["existing_agent_configuration_preserved"], True)
        self.assertEqual(report["previous_revision"], release.BASELINE)
        with (
            patch.object(release.delivery, "_execute"),
            self.assertRaisesRegex(RuntimeError, "existing_data_verification_missing"),
        ):
            self.stage.execute(None, None, None, {}, [])

    def test_snapshot_covers_existing_ai_sessions_artifacts_and_models(self):
        tables = ["ai_workspace_sessions", "ai_workspace_artifacts", "content_generation_models"]
        with patch.object(
            release.cutover,
            "sql",
            side_effect=[
                json.dumps(tables),
                '["id", "title"]',
                '["id", "content"]',
                '["id", "secret_ciphertext"]',
                "2|sessions",
                "3|artifacts",
                "1|models",
            ],
        ):
            columns, before = self.stage.table_snapshot(None, None)
        self.assertEqual(set(columns), set(tables))
        with patch.object(
            release.cutover, "sql", side_effect=["2|sessions", "3|artifacts", "1|models"]
        ) as query:
            self.assertEqual(self.stage.table_snapshot(None, None, columns)[1], before)
            self.assertEqual(query.call_count, 3)
        with patch.object(
            release.cutover, "sql", side_effect=["2|sessions", "3|changed", "1|models"]
        ):
            self.assertNotEqual(self.stage.table_snapshot(None, None, columns)[1], before)

    def test_recovery_uses_saved_baseline_and_rejects_different_target(self):
        f = self.fixture
        f.save(f.inventory / "current-release-before.json", self.record)
        manifest = {
            "commit": release.REVISION,
            "version": release.VERSION,
            "previous_commit": release.BASELINE,
        }
        f.save(f.out / "release-manifest.json", manifest)
        with patch.object(release.delivery, "_recover_record") as recover:
            self.stage.recover_record(f.runner, f.inventory, f.out)
            recover.assert_called_once_with(f.runner, f.inventory, f.out)
            for change in (
                {"commit": release.BASELINE},
                {"version": "v1.6.0"},
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

    def test_same_schema_finalize_validates_live_release_and_reports_no_schema_change(self):
        f = self.fixture
        release.select_profile(self.record)
        images = {"backend": "sha256:" + "a" * 64, "frontend": "sha256:" + "b" * 64}
        configs = {
            name: {
                "Image": f.old[name]["Image"]
                if name in self.stage.INFRA
                else images["frontend" if name == "kap-frontend-1" else "backend"],
                "Labels": {LABEL: f.out.name},
            }
            for name in self.stage.START
        }
        state = {
            "new": {name: f"{index:064x}" for index, name in enumerate(self.stage.START, 100)},
            "originals": {name: f.old[name] for name in self.stage.ORIGINAL_START},
            "traffic_opening": True,
            "backup_complete": True,
            "data_mutated": True,
        }
        report = {
            "phase": "production_stage_rollout",
            "revision": release.REVISION,
            "version": release.VERSION,
            "production_switched": True,
            "manual_recovery_required": True,
        }
        for name, value in {
            "state-private.json": state,
            "report.json": report,
            "runtime-private.json": f.old,
            "candidate-image-ids.json": images,
            "candidate-runtime-private.json": configs,
        }.items():
            f.save(f.out / name, value)
        current = {
            name: {
                "Id": state["new"][name],
                "Name": "/" + name,
                "Image": config["Image"],
                "Config": {"Labels": config["Labels"]},
                "State": {"Running": True, "Health": {"Status": "healthy"}},
            }
            for name, config in configs.items()
        }
        runner = Mock()
        runner.inspect.side_effect = lambda name: current.get(name, f.old.get(name))
        runner.docker.return_value = ""
        with (
            patch.object(
                self.stage,
                "sql",
                side_effect=lambda _r, _old, query: (
                    release.SCHEMA if query == "SELECT version_num FROM alembic_version;" else "1"
                ),
            ) as query,
            patch.object(finish, "public_health") as health,
            patch.object(finish, "check_managed_compose", return_value=f.managed),
            patch.object(finish, "source_state", return_value=release.REVISION),
            patch.object(finish.Runtime, "configure_entrypoints"),
            patch.object(finish.Runtime, "save"),
        ):
            result = {}
            finish.finalize(runner, f.out, result)
            self.assertIs(result["passed"], True)
            self.assertIs(result["database_schema_changed"], False)
            self.assertEqual(result["migration_target"], "0096_ai_workspace")
            updated = json.loads((f.out / "report.json").read_text())
            self.assertIs(updated["database_schema_changed"], False)
            self.assertNotIn("manual_recovery_required", updated)
            self.assertGreaterEqual(health.call_count, 2)
            query.side_effect = lambda *args: "0095_knowledge_tasks"
            with self.assertRaisesRegex(RuntimeError, "live_schema_changed"):
                finish.verify_live(runner, f.out, state, f.old, configs)
        runner.execute.assert_not_called()
        runner.capture.assert_not_called()
        f.save(f.out / "state-private.json", {**state, "traffic_opening": False})
        with self.assertRaisesRegex(RuntimeError, "not_opened_rollout"):
            finish.validate_records(f.out)


if __name__ == "__main__":
    unittest.main()

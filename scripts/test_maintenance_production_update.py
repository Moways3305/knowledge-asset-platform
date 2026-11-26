"""Exercise baseline discovery against the actual rollout validator, without Docker."""

import ast
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import deploy_maintenance_update as release
import deploy_stage_release as stage
from test_production_stage_rollout import original


class MaintenanceDelivery(unittest.TestCase):
    def setUp(self):
        self.apply(patch.dict(stage.__dict__))
        release.configure()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.apply(patch.object(stage, "ROOT", self.root))
        self.inventory = self.root / "inventory-maintenance-fixture"
        self.inventory.mkdir()
        self.prior = self.root / "release-1234567890"
        self.prior.mkdir()
        self.managed = self.prior / "kap-compose-private.json"
        self.out = self.root / "release-0987654321"
        self.out.mkdir()
        self.baseline = "c7c29430219933c0336e8280788dcb799f6253ab"
        self.names = (
            *stage.START,
            "kap-migrate-1",
            *("WeKnora-" + s for s in ("app", "frontend", "docreader", "postgres", "redis")),
        )
        self.old = {name: original(name) for name in self.names}
        for item in self.old.values():
            item["State"]["Health"] = {"Status": "healthy"}
            item["Config"]["Labels"]["com.docker.compose.project.config_files"] = str(self.managed)
        self.save(
            self.managed,
            {
                "services": {
                    name[4:-2]: {
                        "image": self.old[name]["Image"],
                        "environment": dict(
                            v.split("=", 1) for v in self.old[name]["Config"]["Env"]
                        ),
                    }
                    for name in stage.START
                }
            },
        )
        self.set_baseline(self.baseline)
        self.runner = Mock()
        self.runner.inspect.side_effect = lambda name: copy.deepcopy(self.old[name])
        self.runner.image_identity.side_effect = lambda value: value
        self.runner.docker.side_effect = self.docker
        self.git_mock = self.apply(patch.object(stage, "git", side_effect=self.git))
        self.sql_mock = self.apply(patch.object(stage, "sql", side_effect=self.sql))
        self.health = self.apply(patch.object(stage, "public_health"))

    def apply(self, context):
        value = context.start()
        self.addCleanup(context.stop)
        return value

    @staticmethod
    def save(path, value):
        path.write_text(json.dumps(value), encoding="utf-8")

    def set_baseline(self, revision):
        self.baseline = revision
        version, _ = release.BASELINES[revision]
        self.record = {
            "revision": revision,
            "version": version,
            "managed_compose_file": str(self.managed),
            "record_directory": str(self.prior),
        }
        self.save(self.root / "current-release.json", self.record)
        self.save(
            self.prior / "report.json",
            {
                **self.record,
                "passed": True,
                "checkpoint": "complete",
                "production_switched": True,
                "post_deployment_tasks_pending": [],
            },
        )

    def docker(self, *args):
        if args[0] == "compose":
            return self.managed.read_text(encoding="utf-8")
        if args[:2] == ("ps", "-a"):
            return "\n".join(self.old)
        if args[:2] == ("exec", "kap-postgres-1"):
            return ""
        raise AssertionError(f"Unexpected Docker operation: {args[:2]}")

    def git(self, runner, *args):
        if args == ("rev-parse", "HEAD"):
            return self.baseline
        if args == ("status", "--porcelain") or args[0] == "merge-base":
            return ""
        raise AssertionError("Unexpected Git operation")

    def sql(self, runner, item, query):
        if query == "SELECT version_num FROM alembic_version;":
            return release.BASELINES[self.baseline][1]
        if "pg_tablespace" in query:
            return "0"
        raise AssertionError("Unexpected SQL operation")

    def test_current_130_capture_validates_all_live_state(self):
        self.assertEqual(stage.validate_inventory(self.runner, self.inventory), self.old)
        self.health.assert_called_once_with(
            self.runner,
            self.old["kap-backend-1"]["Id"],
            self.baseline,
            "v1.3.0",
        )
        self.assertEqual(stage.SCHEMA, "0091_maintenance_batch_progress")
        self.assertEqual(stage.BASELINE_SCHEMA, "0090_maintenance_run_details")
        self.assertEqual(len(stage.RELEASE_ENTRIES), 4)
        self.runner.execute.assert_not_called()

    def test_121_capture_carries_skipped_release_notes_and_actual_schema(self):
        self.set_baseline("6f410db1ff1e8479d32470edccc046ccffd7e6be")
        self.assertEqual(stage.validate_inventory(self.runner, self.inventory), self.old)
        self.assertEqual(stage.BASELINE_SCHEMA, "0089_maintenance_agent")
        self.assertEqual(len(stage.RELEASE_ENTRIES), 7)
        self.health.assert_called_once_with(
            self.runner,
            self.old["kap-backend-1"]["Id"],
            self.baseline,
            "v1.2.1",
        )

    def test_unknown_or_already_deployed_record_stops_before_runtime_access(self):
        for revision, version, error in [
            ("f" * 40, "v1.3.0", "unsupported_baseline"),
            (self.baseline, "v1.2.1", "unsupported_baseline"),
            (release.REVISION, release.VERSION, "release_already_deployed"),
        ]:
            self.save(
                self.root / "current-release.json",
                {**self.record, "revision": revision, "version": version},
            )
            with self.subTest(revision=revision), self.assertRaisesRegex(RuntimeError, error):
                stage.validate_inventory(self.runner, self.inventory)
            self.runner.inspect.assert_not_called()
            self.runner.execute.assert_not_called()

    def test_incomplete_previous_release_stops_without_building(self):
        for change in [
            {"passed": False},
            {"checkpoint": "opening_traffic"},
            {"manual_recovery_required": True},
            {"post_deployment_tasks_pending": ["cleanup"]},
            {"revision": "f" * 40},
        ]:
            self.set_baseline(self.baseline)
            previous = release.read_record(self.prior / "report.json")
            self.save(self.prior / "report.json", {**previous, **change})
            with (
                self.subTest(change=change),
                self.assertRaisesRegex(RuntimeError, "previous_release_incomplete"),
            ):
                stage.validate_inventory(self.runner, self.inventory)
            self.runner.execute.assert_not_called()

    def test_compose_cannot_escape_release_root_or_change_directory(self):
        for changed in [
            {"managed_compose_file": str(self.root / "kap-compose-private.json")},
            {"record_directory": str(self.root)},
        ]:
            with (
                self.subTest(changed=changed),
                self.assertRaisesRegex(RuntimeError, "managed_compose_path_changed"),
            ):
                release.managed_path({**self.record, **changed})

    def test_changed_image_environment_or_health_is_rejected(self):
        for parent, key, value, error in [
            (None, "Image", "unexpected", "managed_image_changed"),
            ("Config", "Env", ["SECRET=changed"], "managed_environment_changed"),
            ("State", "Running", False, "baseline_service_not_healthy"),
        ]:
            old = copy.deepcopy(self.old["kap-backend-1"])
            target = self.old["kap-backend-1"]
            (target if parent is None else target[parent])[key] = value
            with self.subTest(error=error), self.assertRaisesRegex(RuntimeError, error):
                stage.validate_inventory(self.runner, self.inventory)
            self.old["kap-backend-1"] = old

    def test_inventory_schema_and_live_schema_must_match_profile(self):
        self.sql_mock.side_effect = lambda *args: "0083_model_registry"
        with self.assertRaisesRegex(RuntimeError, "unexpected_inventory"):
            stage.validate_inventory(self.runner, self.inventory)
        self.runner.execute.assert_not_called()

    def test_dirty_repository_is_rejected(self):
        self.git_mock.side_effect = lambda runner, *args: (
            " M changed.py" if args == ("status", "--porcelain") else self.git(runner, *args)
        )
        with self.assertRaisesRegex(RuntimeError, "unexpected_inventory"):
            stage.validate_inventory(self.runner, self.inventory)

    def test_recovery_uses_saved_baseline_and_rejects_mismatched_manifest(self):
        self.save(self.inventory / "current-release-before.json", self.record)
        manifest = {
            "commit": release.REVISION,
            "version": release.VERSION,
            "previous_commit": self.baseline,
        }
        self.save(self.out / "release-manifest.json", manifest)
        self.save(
            self.root / "current-release.json",
            {"revision": release.REVISION, "version": release.VERSION},
        )
        with patch.object(release, "_recover_record") as recover:
            release.recover_record(self.runner, self.inventory, self.out)
            recover.assert_called_once_with(self.runner, self.inventory, self.out)
            self.assertEqual(stage.BASELINE, self.baseline)
            recover.reset_mock()
            self.save(self.out / "release-manifest.json", {**manifest, "previous_commit": "f" * 40})
            with self.assertRaisesRegex(RuntimeError, "recovery_release_mismatch"):
                release.recover_record(self.runner, self.inventory, self.out)
            recover.assert_not_called()

    def test_declared_candidate_migration_chain(self):
        root = Path(__file__).resolve().parents[1] / "backend/alembic/versions"
        revisions = {}
        for path in root.glob("*.py"):
            fields = {}
            for node in ast.parse(path.read_text(encoding="utf-8")).body:
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                    fields[node.targets[0].id] = node.value.value
            if "revision" in fields:
                revisions[fields["revision"]] = fields.get("down_revision")
        # This historical helper remains pinned to 0091 even when later
        # delivery branches contain additional application migrations.
        self.assertEqual(revisions[stage.SCHEMA], "0090_maintenance_run_details")
        self.assertEqual(revisions["0090_maintenance_run_details"], "0089_maintenance_agent")


if __name__ == "__main__":
    unittest.main()

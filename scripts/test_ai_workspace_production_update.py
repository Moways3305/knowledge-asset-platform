"""Exercise the real delivery guards for v1.5.0 -> v1.6.0 without production access."""

import asyncio
import copy
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import deploy_ai_workspace_update as release
import finalize_stage_release as finish
import test_maintenance_production_update as fixtures
from production_cutover_runtime import LABEL


class WorkspaceDelivery(unittest.TestCase):
    def setUp(self):
        # Reuse the managed-runtime fixture, not its historical release assertions.
        guard = patch.dict(release.delivery.__dict__)
        guard.start()
        self.addCleanup(guard.stop)
        self.fixture = fixtures.MaintenanceDelivery()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        release.configure()
        self.stage = release.stage
        self.fixture.baseline = release.BASELINE
        self.record = {
            "revision": release.BASELINE,
            "version": release.BASELINE_VERSION,
            "managed_compose_file": str(self.fixture.managed),
            "record_directory": str(self.fixture.prior),
        }
        self.fixture.save(self.fixture.root / "current-release.json", self.record)
        self.fixture.save(
            self.fixture.prior / "report.json",
            {
                **self.record,
                "passed": True,
                "checkpoint": "complete",
                "production_switched": True,
                "post_deployment_tasks_pending": [],
            },
        )
        self.fixture.sql_mock.side_effect = self.sql

    def sql(self, runner, item, query):
        if query == "SELECT version_num FROM alembic_version;":
            return release.BASELINE_SCHEMA
        if "pg_tablespace" in query:
            return "0"
        raise AssertionError("Unexpected SQL operation")

    def test_real_capture_accepts_exact_managed_baseline_and_pins_target(self):
        f = self.fixture
        self.assertEqual(self.stage.validate_inventory(f.runner, f.inventory), f.old)
        self.assertEqual(self.stage.REVISION, "57cd2720d6e2cef035adc6368846f7888bbfafa1")
        self.assertEqual(self.stage.VERSION, "v1.6.0")
        self.assertEqual(self.stage.SCHEMA, "0096_ai_workspace")
        self.assertEqual(self.stage.BASELINE, "07d013228b8decb4651ec3dee44ae01900e8d43f")
        self.assertEqual(self.stage.BASELINE_VERSION, "v1.5.0")
        self.assertEqual(self.stage.BASELINE_SCHEMA, "0095_knowledge_tasks")
        self.assertIs(self.stage.table_snapshot, release.cutover.table_snapshot)
        f.health.assert_called_once_with(
            f.runner, f.old["kap-backend-1"]["Id"], release.BASELINE, "v1.5.0"
        )
        f.runner.execute.assert_not_called()
        captured = json.loads((f.inventory / "report.json").read_text())
        self.assertEqual(captured["migration"], "0095_knowledge_tasks")

    def test_unknown_wrong_version_or_already_deployed_stops_before_inspection(self):
        f = self.fixture
        for revision, version, error in (
            ("f" * 40, release.BASELINE_VERSION, "unsupported_baseline"),
            (release.BASELINE, "v1.4.2", "unsupported_baseline"),
            (release.REVISION, release.VERSION, "release_already_deployed"),
        ):
            f.save(
                f.root / "current-release.json",
                {**self.record, "revision": revision, "version": version},
            )
            with self.subTest(revision=revision), self.assertRaisesRegex(RuntimeError, error):
                self.stage.validate_inventory(f.runner, f.inventory)
            f.runner.inspect.assert_not_called()
            f.runner.execute.assert_not_called()

    def test_managed_image_environment_health_and_previous_completion_cannot_drift(self):
        f = self.fixture
        baseline = copy.deepcopy(f.old["kap-backend-1"])
        for parent, key, value, error in (
            (None, "Image", "unexpected", "managed_image_changed"),
            ("Config", "Env", ["MODEL_KEY=changed"], "managed_environment_changed"),
            ("State", "Running", False, "baseline_service_not_healthy"),
        ):
            target = f.old["kap-backend-1"]
            (target if parent is None else target[parent])[key] = value
            with self.subTest(error=error), self.assertRaisesRegex(RuntimeError, error):
                self.stage.validate_inventory(f.runner, f.inventory)
            f.old["kap-backend-1"] = copy.deepcopy(baseline)
        previous = json.loads((f.prior / "report.json").read_text())
        for change in (
            {"passed": False},
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

    def test_wrong_inventory_schema_rejected_before_build(self):
        f = self.fixture
        f.sql_mock.side_effect = lambda *args: "0093_optional_knowledge_review"
        with self.assertRaisesRegex(RuntimeError, "unexpected_inventory"):
            self.stage.validate_inventory(f.runner, f.inventory)
        f.runner.execute.assert_not_called()

    def test_live_schema_change_after_capture_rejected(self):
        f = self.fixture
        calls = 0

        def changed(runner, item, query):
            nonlocal calls
            if query == "SELECT version_num FROM alembic_version;":
                calls += 1
                return release.BASELINE_SCHEMA if calls == 1 else "0096_ai_workspace"
            return self.sql(runner, item, query)

        f.sql_mock.side_effect = changed
        with self.assertRaisesRegex(RuntimeError, "schema_changed"):
            self.stage.validate_inventory(f.runner, f.inventory)
        f.runner.execute.assert_not_called()

    def test_nine_services_keep_model_environment_resources_and_storage(self):
        self.assertEqual(len(self.stage.START), 9)
        self.assertEqual(self.stage.ORIGINAL_START, self.stage.START)
        self.assertEqual(self.stage.ADDED, ())
        self.assertEqual(self.stage.COMMANDS, {})
        self.assertEqual(self.stage.RESOURCES, {})
        self.assertEqual(set(self.stage.STOP_APPS), set(self.stage.START) - set(self.stage.INFRA))
        old = copy.deepcopy(self.fixture.old)
        for name in self.stage.START:
            if name not in self.stage.INFRA and name != "kap-frontend-1":
                old[name]["Config"]["Env"] += [
                    "CELERY_PARSE_QUEUE=parse",
                    "CELERY_NOTIFICATION_QUEUE=notifications",
                    "GENERATION_MODEL_ENCRYPTION_KEY=synthetic-unchanged-key",
                ]
        runner = Mock()
        runner.docker.side_effect = lambda *args: json.dumps([{"Config": {}}])
        configs = self.stage.deployment_configs(
            runner, old, {"backend": "new-backend", "frontend": "new-frontend"}, self.fixture.out
        )
        for name in self.stage.START:
            config, previous = configs[name], old[name]
            self.assertEqual(sorted(config["Env"]), sorted(previous["Config"]["Env"]))
            for key in ("Cmd", "Entrypoint", "User", "WorkingDir", "Healthcheck", "StopSignal"):
                self.assertEqual(config.get(key), previous["Config"].get(key))
            for key in (
                "NanoCpus",
                "Memory",
                "MemorySwap",
                "MemoryReservation",
                "CpuPeriod",
                "CpuQuota",
                "ShmSize",
            ):
                self.assertEqual(config["HostConfig"].get(key), previous["HostConfig"].get(key))
            self.assertEqual(
                config["HostConfig"]["Mounts"][0]["Source"], previous["Mounts"][0]["Name"]
            )
            if name in self.stage.INFRA:
                self.assertEqual(config["Image"], previous["Image"])
        runner.execute.assert_not_called()

    def test_candidate_environment_mutation_is_rejected(self):
        old = copy.deepcopy(self.fixture.old)
        for name in self.stage.START:
            if name not in self.stage.INFRA and name != "kap-frontend-1":
                old[name]["Config"]["Env"] += [
                    "CELERY_PARSE_QUEUE=parse",
                    "CELERY_NOTIFICATION_QUEUE=notifications",
                ]
        runner = Mock()
        runner.docker.side_effect = lambda *args: json.dumps(
            [{"Config": {"Env": ["NEW_DEFAULT=unexpected"]}}]
        )
        with self.assertRaisesRegex(RuntimeError, "unexpected_environment_change"):
            self.stage.deployment_configs(
                runner,
                old,
                {"backend": "new-backend", "frontend": "new-frontend"},
                self.fixture.out,
            )

    def test_recovery_selects_saved_profile_and_rejects_wrong_target(self):
        f = self.fixture
        f.save(f.inventory / "current-release-before.json", self.record)
        manifest = {
            "commit": release.REVISION,
            "version": release.VERSION,
            "previous_commit": release.BASELINE,
        }
        f.save(f.out / "release-manifest.json", manifest)
        f.save(
            f.root / "current-release.json",
            {"revision": release.REVISION, "version": release.VERSION},
        )
        with patch.object(release.delivery, "_recover_record") as recover:
            release.delivery.recover_record(f.runner, f.inventory, f.out)
            recover.assert_called_once_with(f.runner, f.inventory, f.out)
            self.assertEqual(self.stage.BASELINE, release.BASELINE)
            for change in (
                {"commit": "f" * 40},
                {"version": "v1.5.0"},
                {"previous_commit": "a" * 40},
            ):
                f.save(f.out / "release-manifest.json", {**manifest, **change})
                recover.reset_mock()
                with (
                    self.subTest(change=change),
                    self.assertRaisesRegex(RuntimeError, "recovery_release_mismatch"),
                ):
                    release.delivery.recover_record(f.runner, f.inventory, f.out)
                recover.assert_not_called()

    def test_finalize_records_require_exact_target_and_opened_verified_backup(self):
        f = self.fixture
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
        }
        for name, value in {
            "state-private.json": state,
            "report.json": report,
            "runtime-private.json": f.old,
            "candidate-image-ids.json": images,
            "candidate-runtime-private.json": configs,
        }.items():
            f.save(f.out / name, value)
        self.assertEqual(finish.validate_records(f.out)[0], state)
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
        with (
            patch.object(
                self.stage,
                "sql",
                side_effect=lambda _r, _old, query: (
                    release.SCHEMA if query == "SELECT version_num FROM alembic_version;" else "1"
                ),
            ) as query,
            patch.object(finish, "public_health") as health,
        ):
            self.assertEqual(len(finish.verify_live(runner, f.out, state, f.old, configs)), 9)
            health.assert_called_once_with(
                runner, state["new"]["kap-backend-1"], release.REVISION, release.VERSION
            )
            query.side_effect = lambda *args: release.BASELINE_SCHEMA
            with self.assertRaisesRegex(RuntimeError, "live_schema_changed"):
                finish.verify_live(runner, f.out, state, f.old, configs)
        runner.execute.assert_not_called()
        for change in (
            {"revision": release.BASELINE},
            {"version": "v1.5.0"},
            {"production_switched": False},
        ):
            f.save(f.out / "report.json", {**report, **change})
            with (
                self.subTest(change=change),
                self.assertRaisesRegex(RuntimeError, "unexpected_release_record"),
            ):
                finish.validate_records(f.out)
        f.save(f.out / "report.json", report)
        f.save(f.out / "state-private.json", {**state, "backup_complete": False})
        with self.assertRaisesRegex(RuntimeError, "not_opened_rollout"):
            finish.validate_records(f.out)

    def test_snapshot_freezes_old_columns_without_requiring_new_tables(self):
        with patch.object(
            release.cutover,
            "sql",
            side_effect=[
                '["users", "content_generation_models"]',
                '["id"]',
                '["id", "secret_ciphertext"]',
                "1|users",
                "1|models",
            ],
        ):
            columns, before = self.stage.table_snapshot(None, None)
        self.assertEqual(set(columns), {"users", "content_generation_models"})
        with patch.object(release.cutover, "sql", side_effect=["1|users", "1|models"]) as query:
            self.assertEqual(self.stage.table_snapshot(None, None, columns)[1], before)
            self.assertEqual(query.call_count, 2)
        self.assertFalse(any(name.startswith("ai_workspace_") for name in columns))


@unittest.skipUnless(
    os.environ.get("KAP_CUTOVER_TEST_DATABASE_URL"), "requires disposable empty PostgreSQL"
)
class WorkspacePostgresSnapshot(unittest.TestCase):
    def test_actual_0096_preserves_models_and_existing_rows(self):
        from sqlalchemy.ext.asyncio import create_async_engine

        async def run():
            engine = create_async_engine(os.environ["KAP_CUTOVER_TEST_DATABASE_URL"])
            try:
                async with engine.connect() as connection:
                    async with connection.begin() as transaction:
                        await connection.run_sync(self.check_migration)
                        await transaction.rollback()
            finally:
                await engine.dispose()

        asyncio.run(run())

    def check_migration(self, connection):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        sql = connection.exec_driver_sql
        self.assertEqual(
            sql("SELECT count(*) FROM pg_tables WHERE schemaname='public'").scalar_one(), 0
        )
        sql("CREATE TABLE users (id uuid PRIMARY KEY)")
        sql("CREATE TABLE content_generation_models (id uuid PRIMARY KEY, secret_ciphertext text)")
        sql("INSERT INTO users VALUES ('00000000-0000-0000-0000-000000000001')")
        sql(
            "INSERT INTO content_generation_models VALUES ('00000000-0000-0000-0000-000000000001', 'synthetic-ciphertext')"
        )

        def query(_runner, _old, statement):
            return "\n".join(
                "|".join(
                    json.dumps(value) if isinstance(value, (dict, list)) else str(value)
                    for value in row
                )
                for row in sql(statement)
            )

        path = Path(__file__).resolve().parents[1] / "backend/alembic/versions/0096_ai_workspace.py"
        spec = importlib.util.spec_from_file_location("workspace_deployment_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with (
            patch.object(release.cutover, "sql", side_effect=query),
            Operations.context(MigrationContext.configure(connection)),
        ):
            columns, before = release.cutover.table_snapshot(None, None)
            migration.upgrade()
            self.assertEqual(release.cutover.table_snapshot(None, None, columns)[1], before)
            self.assertEqual(
                sql(
                    "SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'ai_workspace_%'"
                ).scalar_one(),
                5,
            )
            with connection.begin_nested() as savepoint:
                sql("UPDATE content_generation_models SET secret_ciphertext='changed'")
                self.assertNotEqual(release.cutover.table_snapshot(None, None, columns)[1], before)
                savepoint.rollback()
            migration.downgrade()
            self.assertEqual(release.cutover.table_snapshot(None, None, columns)[1], before)
            self.assertEqual(
                sql(
                    "SELECT count(*) FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'ai_workspace_%'"
                ).scalar_one(),
                0,
            )


if __name__ == "__main__":
    unittest.main()

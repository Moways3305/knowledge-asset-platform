"""Verify the release profile and the 0093 -> 0095 data comparison."""

import asyncio
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import deploy_knowledge_task_update as release


class KnowledgeTaskReleaseTests(unittest.TestCase):
    def setUp(self):
        for module in (release.stage, release.delivery):
            guard = patch.dict(module.__dict__)
            guard.start()
            self.addCleanup(guard.stop)
        release.configure()

    def test_baselines_and_release_entries(self):
        for sha, version in release.BASELINES.items():
            release.select_profile({"revision": sha, "version": version})
            self.assertEqual(release.stage.BASELINE, sha)
            self.assertEqual(release.stage.BASELINE_VERSION, version)
            self.assertEqual(release.stage.BASELINE_SCHEMA, "0093_optional_knowledge_review")
            self.assertEqual(release.stage.SCHEMA, "0095_knowledge_tasks")
            self.assertEqual(len(release.stage.RELEASE_ENTRIES), 3 if version == "v1.4.1" else 2)
        for record in (
            {"revision": release.REVISION, "version": release.VERSION},
            {"revision": sha, "version": "other"},
            {},
        ):
            with self.assertRaises(RuntimeError):
                release.select_profile(record)

    @unittest.skipUnless(
        os.environ.get("KAP_CUTOVER_TEST_DATABASE_URL"), "needs disposable PostgreSQL"
    )
    def test_digest_membership_and_business_data_across_actual_migrations(self):
        from sqlalchemy.ext.asyncio import create_async_engine

        async def run():
            engine = create_async_engine(os.environ["KAP_CUTOVER_TEST_DATABASE_URL"])
            try:
                async with engine.connect() as connection:
                    async with connection.begin() as transaction:
                        await connection.run_sync(self.check_migrations)
                        await transaction.rollback()
            finally:
                await engine.dispose()

        asyncio.run(run())

    def check_migrations(self, connection):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations

        sql = connection.exec_driver_sql
        self.assertEqual(
            sql("SELECT count(*) FROM pg_tables WHERE schemaname='public'").scalar_one(), 0
        )
        for ddl in (
            "users (id uuid PRIMARY KEY)",
            "knowledge_assets (id uuid PRIMARY KEY, asset_status text, deleted_at timestamp, replacement_asset_id uuid, archived_at timestamp)",
            "maintenance_agent_issues (id uuid PRIMARY KEY, rule text, asset_id uuid, status text, updated_at timestamp)",
            "maintenance_agent_issue_events (id uuid PRIMARY KEY, issue_id uuid, action text, created_at timestamp)",
            "maintenance_agent_digests (id uuid PRIMARY KEY, issue_ids json NOT NULL, day text)",
        ):
            sql("CREATE TABLE " + ddl)
        a, b, c, digest, empty = [f"00000000-0000-0000-0000-{i:012d}" for i in range(1, 6)]
        for issue_id in (a, b, c):
            sql(
                f"INSERT INTO maintenance_agent_issues VALUES ('{issue_id}', 'missing_tags', '{a}', 'not_applicable', now())"
            )
        sql(f"INSERT INTO knowledge_assets VALUES ('{a}', 'archived', NULL, '{b}', now())")
        sql(
            f"INSERT INTO maintenance_agent_issue_events VALUES ('{b}', '{a}', 'fact_reconciled', now())"
        )
        sql(
            f"""INSERT INTO maintenance_agent_digests VALUES ('{digest}', '["{b}","{a}","{a}"]', 'first'), ('{empty}', '[]', 'second')"""
        )

        def query(_runner, _old, statement):
            return "\n".join(
                "|".join(json.dumps(v) if isinstance(v, (dict, list)) else str(v) for v in row)
                for row in sql(statement)
            )

        with (
            patch.object(
                release.delivery, "capture_inventory", return_value={release.stage.INFRA[0]: {}}
            ),
            patch.object(release.stage, "sql", side_effect=query),
            patch.object(release.cutover, "sql", side_effect=query),
        ):
            release.validate_inventory(None, None)
            with connection.begin_nested() as sp:
                sql(
                    f"""UPDATE maintenance_agent_digests SET issue_ids='["{empty}"]' WHERE id='{digest}'"""
                )
                with self.assertRaisesRegex(RuntimeError, "unmigratable_digest_members"):
                    release.validate_inventory(None, None)
                sp.rollback()
            snapshot = release.stage.table_snapshot
            columns, before = snapshot(None, None)
            folder = Path(__file__).resolve().parents[1] / "backend/alembic/versions"
            with Operations.context(MigrationContext.configure(connection)):
                for name in ("0094_maintenance_continuity", "0095_knowledge_tasks"):
                    spec = importlib.util.spec_from_file_location(name, folder / f"{name}.py")
                    migration = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(migration)
                    migration.upgrade()
            self.assertEqual(snapshot(None, None, columns)[1], before)
            self.assertEqual(sql("SELECT count(*) FROM knowledge_agent_tasks").scalar_one(), 0)
            self.assertEqual(
                str(
                    sql(
                        "SELECT id FROM maintenance_agent_issues WHERE requires_recheck"
                    ).scalar_one()
                ),
                a,
            )
            for mutation in (
                f"UPDATE maintenance_digest_issues SET issue_id='{c}' WHERE issue_id='{a}'",
                f"UPDATE maintenance_digest_issues SET digest_id='{empty}' WHERE issue_id='{b}'",
                "DELETE FROM maintenance_digest_issues",
                "UPDATE maintenance_agent_digests SET day='changed'",
                "UPDATE maintenance_agent_issues SET status='changed'",
            ):
                with self.subTest(mutation=mutation), connection.begin_nested() as sp:
                    sql(mutation)
                    self.assertNotEqual(snapshot(None, None, columns)[1], before)
                    sp.rollback()

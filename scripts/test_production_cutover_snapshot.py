"""Snapshot guards and real PostgreSQL coverage of the actual 0083 migration."""

import asyncio
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import execute_production_cutover as cutover


class SnapshotProjectionTests(unittest.TestCase):
    def test_baseline_columns_are_quoted_and_reused_without_rediscovery(self):
        with patch.object(
            cutover,
            "sql",
            side_effect=['["models"]', '["id", "odd\\"name"]', "1|before"],
        ) as sql:
            columns, before = cutover.table_snapshot(None, None)
            self.assertEqual(columns, {"models": '"id","odd""name"'})
            self.assertIn('SELECT "id","odd""name" FROM public."models"', sql.call_args.args[2])
        with patch.object(cutover, "sql", return_value="1|before") as sql:
            self.assertEqual(cutover.table_snapshot(None, None, columns)[1], before)
            self.assertEqual(sql.call_count, 1)

    def test_unreadable_original_columns_fail_closed(self):
        with patch.object(cutover, "sql", side_effect=['["models"]', "[]"]):
            with self.assertRaisesRegex(RuntimeError, "no readable columns"):
                cutover.table_snapshot(None, None)


@unittest.skipUnless(
    os.environ.get("KAP_CUTOVER_TEST_DATABASE_URL"),
    "requires a disposable empty PostgreSQL database",
)
class PostgreSQLSnapshotMigrationTests(unittest.TestCase):
    def test_0083_added_columns_pass_but_original_data_changes_fail(self):
        from sqlalchemy.ext.asyncio import create_async_engine

        async def run():
            engine = create_async_engine(os.environ["KAP_CUTOVER_TEST_DATABASE_URL"])
            try:
                async with engine.connect() as connection:
                    transaction = await connection.begin()
                    try:
                        await connection.run_sync(self.verify_migration)
                    finally:
                        # All fixtures and DDL are rolled back, including on assertion failure.
                        await transaction.rollback()
            finally:
                await engine.dispose()

        asyncio.run(run())

    def verify_migration(self, connection):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from sqlalchemy.exc import DBAPIError

        self.assertEqual(
            connection.exec_driver_sql(
                "SELECT count(*) FROM pg_tables WHERE schemaname='public'"
            ).scalar_one(),
            0,
            "Only run this regression against an empty disposable database",
        )
        connection.exec_driver_sql(
            "CREATE TABLE content_generation_models (id uuid PRIMARY KEY, name text, "
            "secret_ciphertext text, metadata jsonb, optional_value text)"
        )
        connection.exec_driver_sql(
            "INSERT INTO content_generation_models VALUES "
            "('00000000-0000-0000-0000-000000000001', '虚构模型', 'synthetic-ciphertext', "
            "'{\"enabled\":true}'::jsonb, NULL)"
        )
        connection.exec_driver_sql('CREATE TABLE "odd\'table" ("odd""column" text)')
        connection.exec_driver_sql("INSERT INTO \"odd'table\" VALUES ('synthetic')")

        def query(_runner, _old, sql):
            rows = connection.exec_driver_sql(sql).fetchall()
            return "\n".join(
                "|".join(
                    json.dumps(value) if isinstance(value, (dict, list)) else str(value)
                    for value in row
                )
                for row in rows
            )

        with patch.object(cutover, "sql", side_effect=query):
            columns, before = cutover.table_snapshot(None, None)
            legacy = {table: "*" for table in columns}
            self.assertEqual(cutover.table_snapshot(None, None, legacy)[1], before)
            path = (
                Path(__file__).resolve().parents[1]
                / "backend/alembic/versions/0083_model_registry.py"
            )
            spec = importlib.util.spec_from_file_location("migration_0083", path)
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()

            self.assertEqual(
                connection.exec_driver_sql(
                    "SELECT config_version, tested_version FROM content_generation_models"
                ).one(),
                (1, None),
            )
            # Reproduce the production false positive with the former SELECT * logic.
            self.assertNotEqual(cutover.table_snapshot(None, None, legacy)[1], before)
            self.assertEqual(cutover.table_snapshot(None, None, columns)[1], before)
            self.assertNotIn("registered_models", columns)

            for mutation in (
                "UPDATE content_generation_models SET name='changed'",
                "UPDATE content_generation_models SET secret_ciphertext='changed'",
                "UPDATE content_generation_models SET optional_value=''",
                "DELETE FROM content_generation_models",
                "INSERT INTO content_generation_models (id, name) VALUES "
                "('00000000-0000-0000-0000-000000000002', 'extra')",
            ):
                with self.subTest(mutation=mutation):
                    savepoint = connection.begin_nested()
                    try:
                        connection.exec_driver_sql(mutation)
                        self.assertNotEqual(cutover.table_snapshot(None, None, columns)[1], before)
                    finally:
                        savepoint.rollback()
                    self.assertEqual(cutover.table_snapshot(None, None, columns)[1], before)

            savepoint = connection.begin_nested()
            try:
                connection.exec_driver_sql("ALTER TABLE content_generation_models DROP COLUMN name")
                with self.assertRaises(DBAPIError):
                    cutover.table_snapshot(None, None, columns)
            finally:
                savepoint.rollback()


if __name__ == "__main__":
    unittest.main()

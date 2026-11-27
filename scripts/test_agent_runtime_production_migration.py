"""Migration preservation checks, including real PostgreSQL 0097/0098 execution."""

import asyncio
from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid

import agent_runtime_migration_check as check


class MigrationManifest(unittest.TestCase):
    def test_expected_identity_collision_stops_before_snapshot(self):
        task = str(uuid.uuid4())
        with (
            patch.object(check.cutover, "sql", side_effect=[json.dumps([task]), "1"]),
            patch.object(check.cutover, "table_snapshot") as snapshot,
            self.assertRaisesRegex(RuntimeError, "legacy_agent_import_identity_conflict"),
        ):
            check.table_snapshot(None, None)
        snapshot.assert_not_called()

    def test_manifest_does_not_exempt_any_business_table(self):
        task = str(uuid.uuid4())
        tables = {name: '"id"' for name in (*check.TABLE_KEYS, "users", "knowledge_agent_tasks")}
        before = {name: "1|unchanged" for name in tables}
        with (
            patch.object(check.cutover, "sql", side_effect=[json.dumps([task]), "0"]),
            patch.object(check.cutover, "table_snapshot", return_value=(tables, before)),
        ):
            manifest, digest = check.table_snapshot(None, None)
        self.assertEqual(digest, before)
        self.assertEqual(manifest["imports"], [task])
        with (
            patch.object(check.cutover, "sql", return_value="0"),
            patch.object(
                check.cutover, "table_snapshot", return_value=(tables, before)
            ) as snapshot,
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(check.table_snapshot(None, None, manifest)[1], before)
        self.assertEqual(snapshot.call_args.args[2], tables)
        predicate = snapshot.call_args.kwargs["row_filter"]
        self.assertEqual(predicate("users"), "true")
        self.assertEqual(predicate("knowledge_agent_tasks"), "true")
        self.assertIn(task, predicate("ai_workspace_sessions"))
        row = check.identities([task])[0]
        self.assertIn(row["run_id"], predicate("ai_workspace_runs"))
        self.assertIn(row["user_id"], predicate("ai_workspace_messages"))
        self.assertIn(row["assistant_id"], predicate("ai_workspace_messages"))

    def test_empty_legacy_history_keeps_all_rows(self):
        tables = {name: '"id"' for name in check.TABLE_KEYS}
        manifest = {"format": check.FORMAT, "tables": tables, "imports": []}
        with (
            patch.object(check.cutover, "sql", return_value="0"),
            patch.object(check.cutover, "table_snapshot", return_value=(tables, {})) as snapshot,
            redirect_stdout(io.StringIO()),
        ):
            check.table_snapshot(None, None, manifest)
        predicate = snapshot.call_args.kwargs["row_filter"]
        self.assertTrue(all(predicate(name) == "true" for name in tables))

    def test_invalid_or_duplicate_uuid_manifest_rejected(self):
        value = str(uuid.uuid4())
        for ids in (None, [value, value], ["not-a-uuid"]):
            with self.subTest(ids=ids), self.assertRaises((RuntimeError, ValueError)):
                check.identities(ids)

    def test_candidate_code_is_bounded_and_read_only(self):
        code = check.redaction_check_code()
        compile(code, "candidate-redaction-check", "exec")
        self.assertLess(len(code.encode()), 12000)
        self.assertIn("SET TRANSACTION READ ONLY", code)
        self.assertIn("/migration-check/database-before-private.json", code)
        self.assertIn("agent_runtime_redaction_verification_failed", code)
        self.assertNotIn("traceback", code)


@unittest.skipUnless(
    os.environ.get("KAP_CUTOVER_TEST_DATABASE_URL"), "requires disposable empty PostgreSQL"
)
class MigrationPostgres(unittest.TestCase):
    def test_real_migration_preserves_originals_and_rejects_import_tampering(self):
        from sqlalchemy.ext.asyncio import create_async_engine

        async def run():
            engine = create_async_engine(os.environ["KAP_CUTOVER_TEST_DATABASE_URL"])
            try:
                async with engine.connect() as connection:
                    async with connection.begin() as transaction:
                        manifest = await connection.run_sync(self.check_migration)
                        namespace = {}
                        # Execute the exact generated candidate verification function
                        # against this real transaction; the deployment entrypoint
                        # separately opens its own explicitly read-only transaction.
                        code = check.redaction_check_code().split("try:\n    manifest =", 1)[0]
                        exec(compile(code, "candidate-redaction-check", "exec"), namespace)
                        await namespace["verify"](connection, manifest["imports"])
                        from sqlalchemy import text

                        for table, field in (
                            ("ai_workspace_sessions", "title"),
                            ("ai_workspace_runs", "instruction"),
                            ("ai_workspace_messages", "content"),
                        ):
                            with self.subTest(redaction_table=table):
                                async with connection.begin_nested() as savepoint:
                                    await connection.execute(
                                        text(
                                            f"UPDATE {table} SET {field}='synthetic-sensitive-original' "
                                            + (
                                                "WHERE id=CAST(:id AS uuid)"
                                                if table == "ai_workspace_sessions"
                                                else "WHERE session_id=CAST(:id AS uuid)"
                                            )
                                        ),
                                        {"id": manifest["imports"][0]},
                                    )
                                    with self.assertRaisesRegex(
                                        RuntimeError, "agent_import_redaction_mismatch"
                                    ):
                                        await namespace["verify"](connection, manifest["imports"])
                                    await savepoint.rollback()
                        await transaction.rollback()
            finally:
                await engine.dispose()

        asyncio.run(run())

    def check_migration(self, connection):
        import sqlalchemy as sa
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from alembic.script import ScriptDirectory

        root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(root / "backend"))
        self.addCleanup(lambda: sys.path.remove(str(root / "backend")))
        scripts = ScriptDirectory(str(root / "backend/alembic"))
        sql = connection.exec_driver_sql
        self.assertEqual(
            sql("SELECT count(*) FROM pg_tables WHERE schemaname='public'").scalar_one(), 0
        )
        sql("CREATE TABLE users (id uuid PRIMARY KEY)")
        sql("CREATE TABLE content_generation_models (id uuid PRIMARY KEY, secret_ciphertext text)")
        owner, session_id, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        sql(f"INSERT INTO users VALUES ('{owner}')")
        sql(
            f"INSERT INTO content_generation_models VALUES ('{uuid.uuid4()}', 'synthetic-model-key')"
        )
        now = datetime(2026, 11, 27, tzinfo=timezone.utc)
        with Operations.context(MigrationContext.configure(connection)):
            scripts.get_revision("0095_knowledge_tasks").module.upgrade()
            scripts.get_revision("0096_ai_workspace").module.upgrade()

        def table(name):
            return sa.Table(name, sa.MetaData(), autoload_with=connection)

        sessions, runs, messages, artifacts = (
            table("ai_workspace_" + name) for name in ("sessions", "runs", "messages", "artifacts")
        )
        connection.execute(
            sessions.insert().values(
                id=session_id,
                user_id=owner,
                role="consultant",
                title="Existing conversation",
                active_run_id=run_id,
                event_seq=3,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            runs.insert().values(
                id=run_id,
                session_id=session_id,
                status="completed",
                model_ref="saved-model",
                context_key="company",
                instruction="Existing instruction",
                source_refs=[{"asset_id": str(uuid.uuid4()), "revision": 2}],
                created_at=now,
            )
        )
        connection.execute(
            messages.insert().values(
                id=uuid.uuid4(),
                session_id=session_id,
                run_id=run_id,
                role="user",
                content="Existing private message",
                created_at=now,
            )
        )
        connection.execute(
            artifacts.insert().values(
                id=uuid.uuid4(),
                session_id=session_id,
                run_id=run_id,
                title="User draft",
                content="Do not replace this draft",
                revision=3,
                created_at=now,
                updated_at=now,
            )
        )
        legacy = table("knowledge_agent_tasks")
        # Include an existing same-ID conversation and cross the 200-row page.
        records = [
            {
                "id": session_id if index == 0 else uuid.uuid4(),
                "user_id": owner,
                "role": "consultant",
                "library_key": "company",
                "instruction": "检查资料，电话13800138000",
                "status": "ready" if index % 2 else "checking",
                "result": {"selected": "private-old-result"},
                "created_at": now,
            }
            for index in range(206)
        ]
        connection.execute(legacy.insert(), records)

        def query(_runner, _old, statement):
            return "\n".join(
                "|".join(json.dumps(v) if isinstance(v, (dict, list)) else str(v) for v in row)
                for row in sql(statement)
            )

        with patch.object(check.cutover, "sql", side_effect=query), redirect_stdout(io.StringIO()):
            # A deterministic future run ID already belonging to an old session
            # must not be silently excluded from preservation checks.
            collision = uuid.UUID(check.identities([str(records[1]["id"])])[0]["run_id"])
            with connection.begin_nested() as savepoint:
                connection.execute(
                    runs.insert().values(
                        id=collision,
                        session_id=session_id,
                        status="completed",
                        model_ref="saved",
                        instruction="Original collision record",
                        source_refs=[],
                        created_at=now,
                    )
                )
                with self.assertRaisesRegex(RuntimeError, "legacy_agent_import_identity_conflict"):
                    check.table_snapshot(None, None)
                savepoint.rollback()
            manifest, before = check.table_snapshot(None, None)
            self.assertEqual(len(manifest["imports"]), 205)
            self.assertNotIn(str(session_id), manifest["imports"])
            with Operations.context(MigrationContext.configure(connection)):
                scripts.get_revision("0097_agent_runtime").module.upgrade()
                scripts.get_revision("0098_legacy_agent_sessions").module.upgrade()
            self.assertEqual(check.table_snapshot(None, None, manifest)[1], before)
            target = manifest["imports"][0]
            for statement, expected_error in (
                (
                    f"DELETE FROM ai_workspace_messages WHERE session_id='{target}'",
                    "legacy_agent_import_mismatch",
                ),
                (
                    f"UPDATE ai_workspace_sessions SET role='general_manager' WHERE id='{target}'",
                    "legacy_agent_import_mismatch",
                ),
                (
                    f"UPDATE ai_workspace_runs SET status='queued' WHERE session_id='{target}'",
                    "legacy_agent_import_mismatch",
                ),
                (
                    f"UPDATE ai_workspace_runs SET claim='{uuid.uuid4()}' WHERE session_id='{target}'",
                    "legacy_agent_import_mismatch",
                ),
                (
                    f"UPDATE ai_workspace_sessions SET agent_key=NULL WHERE id='{session_id}'",
                    "legacy_agent_session_identity_mismatch",
                ),
                (
                    f"UPDATE ai_workspace_artifacts SET source_refs='[]' WHERE session_id='{session_id}'",
                    "agent_provenance_backfill_mismatch",
                ),
            ):
                with self.subTest(statement=statement.split(" WHERE")[0]):
                    with connection.begin_nested() as savepoint:
                        sql(statement)
                        with self.assertRaisesRegex(RuntimeError, expected_error):
                            check.table_snapshot(None, None, manifest)
                        savepoint.rollback()
            for statement in (
                f"UPDATE ai_workspace_sessions SET title='lost-original' WHERE id='{session_id}'",
                f"DELETE FROM ai_workspace_messages WHERE session_id='{session_id}'",
                "UPDATE content_generation_models SET secret_ciphertext='changed'",
                "UPDATE knowledge_agent_tasks SET instruction='changed'",
                f"INSERT INTO ai_workspace_messages (id,session_id,run_id,role,content,created_at,source_refs) "
                f"SELECT '{uuid.uuid4()}',session_id,id,'assistant','unexpected',created_at,source_refs "
                f"FROM ai_workspace_runs WHERE session_id='{target}'",
            ):
                with self.subTest(preservation=statement.split(" WHERE")[0]):
                    with connection.begin_nested() as savepoint:
                        sql(statement)
                        self.assertNotEqual(check.table_snapshot(None, None, manifest)[1], before)
                        savepoint.rollback()
        return manifest


if __name__ == "__main__":
    unittest.main()

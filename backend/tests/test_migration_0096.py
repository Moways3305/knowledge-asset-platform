"""The workspace migration must replay cleanly without touching existing knowledge."""

from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from app.db.base import Base


def test_workspace_migration_matches_metadata_and_replays():
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "alembic"))
    migration = scripts.get_revision("0096_ai_workspace").module
    runtime = scripts.get_revision("0097_agent_runtime").module
    expected = {
        name: table
        for name, table in Base.metadata.tables.items()
        if name.startswith("ai_workspace_")
    }
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE users (id TEXT PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO users (id) VALUES ('existing-user')")
        with Operations.context(MigrationContext.configure(connection)):
            for _ in range(2):
                migration.upgrade()
                runtime.upgrade()
                inspector = sa.inspect(connection)
                assert set(inspector.get_table_names()) == {"users", *expected}
                for name, table in expected.items():
                    columns = {column["name"]: column for column in inspector.get_columns(name)}
                    assert set(columns) == set(table.columns.keys())
                    for column in table.columns:
                        assert columns[column.name]["nullable"] == column.nullable
                    assert {item["name"] for item in inspector.get_indexes(name)} == {
                        index.name for index in table.indexes
                    }
                runtime.downgrade()
                migration.downgrade()
                assert sa.inspect(connection).get_table_names() == ["users"]
                assert connection.exec_driver_sql("SELECT id FROM users").all() == [
                    ("existing-user",)
                ]
    engine.dispose()


def test_runtime_upgrade_preserves_existing_draft_provenance():
    import json

    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "alembic"))
    old = scripts.get_revision("0096_ai_workspace").module
    runtime = scripts.get_revision("0097_agent_runtime").module
    refs = [
        {
            "asset_id": "11111111-2222-4333-8444-123456789012",
            "version_id": "11111111-2222-4333-8444-123456789012",
            "context_key": "company",
            "projection_digest": "old-digest",
        }
    ]
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE users (id TEXT PRIMARY KEY)")
        with Operations.context(MigrationContext.configure(connection)):
            old.upgrade()
            connection.exec_driver_sql(
                "INSERT INTO ai_workspace_sessions (id,user_id,role,title,event_seq,created_at,updated_at) VALUES ('s','u','consultant','old',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
            connection.exec_driver_sql(
                "INSERT INTO ai_workspace_runs (id,session_id,status,model_ref,instruction,source_refs,created_at) VALUES ('r','s','completed','default','old',?,CURRENT_TIMESTAMP)",
                (json.dumps(refs),),
            )
            connection.exec_driver_sql(
                "INSERT INTO ai_workspace_messages (id,session_id,run_id,role,content,created_at) VALUES ('m','s','r','assistant','old result',CURRENT_TIMESTAMP)"
            )
            connection.exec_driver_sql(
                "INSERT INTO ai_workspace_artifacts (id,session_id,run_id,title,content,revision,created_at,updated_at) VALUES ('a','s','r','old draft','old result',1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
            runtime.upgrade()
            for table in ("ai_workspace_messages", "ai_workspace_artifacts"):
                assert (
                    json.loads(
                        connection.exec_driver_sql(f"SELECT source_refs FROM {table}").scalar_one()
                    )
                    == refs
                )
            runtime.downgrade()
            old.downgrade()
    engine.dispose()

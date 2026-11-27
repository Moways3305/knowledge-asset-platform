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
                migration.downgrade()
                assert sa.inspect(connection).get_table_names() == ["users"]
                assert connection.exec_driver_sql("SELECT id FROM users").all() == [
                    ("existing-user",)
                ]
    engine.dispose()

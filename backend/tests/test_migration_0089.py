"""Replay the maintenance migrations and verify their tables against the ORM."""

from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from app.db.base import Base


def test_maintenance_migration_matches_metadata_and_replays():
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[1] / "alembic"))
    migrations = [
        scripts.get_revision(revision).module
        for revision in (
            "0089_maintenance_agent",
            "0090_maintenance_run_details",
            "0091_maintenance_batch_progress",
            "0094_maintenance_continuity",
        )
    ]
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        # 0094 reads the pre-existing asset lifecycle to identify replacement rechecks.
        conn.exec_driver_sql(
            "CREATE TABLE knowledge_assets (id TEXT PRIMARY KEY, asset_status TEXT, "
            "deleted_at DATETIME, replacement_asset_id TEXT, archived_at DATETIME)"
        )
        conn.exec_driver_sql(
            "INSERT INTO knowledge_assets (id, asset_status) VALUES ('seed', 'active')"
        )
        expected = {
            name: set(table.columns.keys())
            for name, table in Base.metadata.tables.items()
            if name.startswith("maintenance_")
        }
        with Operations.context(MigrationContext.configure(conn)):
            for _ in range(2):
                for migration in migrations:
                    migration.upgrade()
                inspector = sa.inspect(conn)
                assert set(inspector.get_table_names()) == {"knowledge_assets", *expected}
                for name, columns in expected.items():
                    assert {col["name"] for col in inspector.get_columns(name)} == columns
                for migration in reversed(migrations):
                    migration.downgrade()
                assert sa.inspect(conn).get_table_names() == ["knowledge_assets"]
                assert conn.exec_driver_sql(
                    "SELECT id, asset_status FROM knowledge_assets"
                ).all() == [("seed", "active")]
    engine.dispose()

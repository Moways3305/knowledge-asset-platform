"""Opt-in feature migration replays and preserves all pre-existing tables."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db.base import Base


def test_maintenance_migration_matches_metadata_and_replays(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/0089_maintenance_agent.py"
    spec = importlib.util.spec_from_file_location("migration_0089", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE existing_assets (value TEXT)"))
        conn.execute(sa.text("INSERT INTO existing_assets VALUES ('preserved')"))
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        for _ in range(2):
            module.upgrade()
            inspector = sa.inspect(conn)
            tables = [
                t for t in Base.metadata.sorted_tables if t.name.startswith("maintenance_agent_")
            ]
            assert len(tables) == 6
            for table in tables:
                assert {c["name"] for c in inspector.get_columns(table.name)} == set(
                    table.columns.keys()
                )
            module.downgrade()
            assert sa.inspect(conn).get_table_names() == ["existing_assets"]
            assert conn.scalar(sa.text("SELECT value FROM existing_assets")) == "preserved"
    engine.dispose()

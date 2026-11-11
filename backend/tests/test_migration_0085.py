"""Scan progress is additive and reversible without modifying business facts."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_scan_progress_migration_preserves_existing_asset(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/0085_governance_scan_batches.py"
    spec = importlib.util.spec_from_file_location("migration_0085", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE knowledge_assets (id TEXT PRIMARY KEY, asset_status TEXT, deleted_at DATETIME, review_due_at DATETIME, updated_at DATETIME)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO knowledge_assets VALUES ('existing', 'active', NULL, '2026-01-01', '2025-01-01')"
            )
        )
        original = tuple(connection.execute(sa.text("SELECT * FROM knowledge_assets")).one())
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(connection)))
        for _ in range(2):
            module.upgrade()
            assert tuple(connection.execute(sa.text("SELECT * FROM knowledge_assets")).one()) == (
                *original,
                None,
                None,
            )
            module.downgrade()
            assert (
                tuple(connection.execute(sa.text("SELECT * FROM knowledge_assets")).one())
                == original
            )
    engine.dispose()

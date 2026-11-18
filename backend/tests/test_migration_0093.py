"""Existing dates and responsibilities survive; upgrades never grant access implicitly."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_optional_review_migration_round_trip(monkeypatch):
    path = (
        Path(__file__).resolve().parents[1] / "alembic/versions/0093_optional_knowledge_review.py"
    )
    spec = importlib.util.spec_from_file_location("migration93", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == "0092_notification_inbox"
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE knowledge_assets (id TEXT PRIMARY KEY, review_due_at TEXT, maintainer_user_id TEXT)"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO knowledge_assets VALUES ('existing', '2026-12-31', 'assigned-user'), ('unscheduled', NULL, NULL)"
            )
        )
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        for _ in range(2):
            module.upgrade()
            rows = (
                conn.execute(sa.text("SELECT * FROM knowledge_assets ORDER BY id")).mappings().all()
            )
            assert rows[0]["review_due_at"] == "2026-12-31"
            assert rows[0]["maintainer_user_id"] == "assigned-user"
            assert all(
                not row["maintenance_delegated"] and row["review_interval_days"] is None
                for row in rows
            )
            module.downgrade()
            assert conn.scalar(sa.text("SELECT COUNT(*) FROM knowledge_assets")) == 2
    engine.dispose()

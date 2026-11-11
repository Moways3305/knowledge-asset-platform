"""Migration rollback preserves facts and refuses to erase unfinished cursors."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_outbox_migration_replay_and_partial_rollback_guard(monkeypatch):
    path = Path(__file__).parents[1] / "alembic/versions/0088_outbox_consumption.py"
    spec = importlib.util.spec_from_file_location("migration_0088", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE domain_event_outbox (id TEXT PRIMARY KEY, status TEXT, payload TEXT)"
            )
        )
        conn.execute(sa.text("INSERT INTO domain_event_outbox VALUES ('event', 'pending', 'keep')"))
        monkeypatch.setattr(module, "op", Operations(MigrationContext.configure(conn)))
        for _ in range(2):
            module.upgrade()
            conn.execute(
                sa.text(
                    "UPDATE domain_event_outbox SET recipient_cursor='123', claim_token='owner'"
                )
            )
            with pytest.raises(RuntimeError, match="Finish partial"):
                module.downgrade()
            assert conn.scalar(sa.text("SELECT claim_token FROM domain_event_outbox")) == "owner"
            conn.execute(sa.text("UPDATE domain_event_outbox SET status='completed'"))
            module.downgrade()
            assert conn.execute(sa.text("SELECT * FROM domain_event_outbox")).all() == [
                ("event", "completed", "keep")
            ]
            conn.execute(sa.text("UPDATE domain_event_outbox SET status='pending'"))
    engine.dispose()

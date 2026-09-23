"""Preserve old announcements; refuse to invent authors on rollback."""

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def load_migration(name):
    path = Path(__file__).parents[1] / "alembic" / "versions" / name
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deployment_migration_preserves_history_and_roundtrips(monkeypatch):
    old = load_migration("0074_release_notes.py")
    new = load_migration("0075_release_deployment.py")
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE users (id TEXT PRIMARY KEY)"))
        connection.execute(sa.text("INSERT INTO users VALUES ('existing')"))
        operations = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(old, "op", operations)
        monkeypatch.setattr(new, "op", operations)
        old.upgrade()
        connection.execute(
            sa.text(
                "INSERT INTO release_notes (id,version,title,entries,notify_users,revision,created_by,created_at,updated_at,published_at) VALUES ('note','v0.1.0','history','[]',1,1,'existing',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        new.upgrade()
        row = connection.execute(
            sa.text("SELECT title,published_at,source_commit,deployed_at FROM release_notes")
        ).one()
        assert row.title == "history" and row.published_at
        assert row.source_commit is None and row.deployed_at is None
        connection.execute(sa.text("UPDATE release_notes SET created_by=NULL"))
        with pytest.raises(RuntimeError, match="Automated"):
            new.downgrade()
        connection.execute(sa.text("UPDATE release_notes SET created_by='existing'"))
        new.downgrade()
        assert "source_commit" not in {
            c["name"] for c in sa.inspect(connection).get_columns("release_notes")
        }
        new.upgrade()
        assert connection.execute(sa.text("SELECT count(*) FROM release_notes")).scalar_one() == 1
    engine.dispose()

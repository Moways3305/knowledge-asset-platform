from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0072_cooperative_upload_cancellation.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0072", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0072_adds_false_cancellation_flag_for_existing_tasks():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE ingest_tasks (id INTEGER PRIMARY KEY)"))
        connection.execute(text("INSERT INTO ingest_tasks (id) VALUES (1)"))
        migration = _load_migration()
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()

        columns = {
            column["name"]: column for column in inspect(connection).get_columns("ingest_tasks")
        }
        assert columns["cancel_requested"]["nullable"] is False
        assert columns["cancellation_cleaned_at"]["nullable"] is True
        assert not connection.execute(
            text("SELECT cancel_requested FROM ingest_tasks WHERE id = 1")
        ).scalar_one()

        migration.downgrade()
        remaining = {column["name"] for column in inspect(connection).get_columns("ingest_tasks")}
        assert "cancel_requested" not in remaining
        assert "cancellation_cleaned_at" not in remaining

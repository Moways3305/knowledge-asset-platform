from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def _load_migration():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0051_upload_sessions.py"
    spec = importlib.util.spec_from_file_location("migration_0051", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0051_upgrade_and_downgrade_upload_session_tables():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id CHAR(32) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE ingest_tasks (id CHAR(32) PRIMARY KEY)"))
        migration = _load_migration()
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()
        inspector = inspect(connection)
        assert {"upload_sessions", "upload_session_items"}.issubset(
            set(inspector.get_table_names())
        )
        assert {column["name"] for column in inspector.get_columns("upload_session_items")} >= {
            "session_id",
            "ingest_task_id",
            "ordinal",
            "batch_index",
            "safe_error_code",
            "same_name_warning",
        }
        indexes = inspector.get_indexes("upload_session_items")
        assert any(
            index["name"] == "uq_upload_session_items_order" and index["unique"]
            for index in indexes
        )

        migration.downgrade()
        assert "upload_sessions" not in inspect(connection).get_table_names()
        assert "upload_session_items" not in inspect(connection).get_table_names()

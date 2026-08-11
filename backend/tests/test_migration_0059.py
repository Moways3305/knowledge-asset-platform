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
        / "0059_canonical_markdown_derivatives.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0059", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0059_upgrade_and_downgrade_canonical_markdown_derivatives():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE ingest_tasks (id CHAR(32) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE knowledge_asset_versions (id CHAR(32) PRIMARY KEY)"))
        migration = _load_migration()
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()
        inspector = inspect(connection)
        assert "ingest_task_derivatives" in inspector.get_table_names()
        columns = {column["name"] for column in inspector.get_columns("ingest_task_derivatives")}
        assert columns >= {
            "ingest_task_id",
            "storage_ref",
            "source_content_hash",
            "content_hash",
            "format_version",
            "status",
            "generated_at",
            "failure_code",
            "linked_version_id",
        }
        assert {index["name"] for index in inspector.get_indexes("ingest_task_derivatives")} >= {
            "ix_ingest_task_derivatives_ingest_task_id",
            "ix_ingest_task_derivatives_linked_version_id",
        }

        migration.downgrade()
        assert "ingest_task_derivatives" not in inspect(connection).get_table_names()

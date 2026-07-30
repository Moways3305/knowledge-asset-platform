"""0050 历史源文件版本关联迁移的 fail-closed 回归测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0050_ingest_task_result_version.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0050", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0050_backfills_only_assets_with_exactly_one_version():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE knowledge_asset_versions (
                    id CHAR(32) PRIMARY KEY,
                    asset_id CHAR(32) NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE knowledge_assets (
                    id CHAR(32) PRIMARY KEY,
                    current_version_id CHAR(32)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ingest_tasks (
                    id CHAR(32) PRIMARY KEY,
                    result_asset_id CHAR(32)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO knowledge_asset_versions (id, asset_id) VALUES
                    ('single-v1', 'single-asset'),
                    ('multi-v1', 'multi-asset'),
                    ('multi-v2', 'multi-asset')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO knowledge_assets (id, current_version_id) VALUES
                    ('single-asset', 'single-v1'),
                    ('multi-asset', 'multi-v2')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO ingest_tasks (id, result_asset_id) VALUES
                    ('single-task', 'single-asset'),
                    ('multi-task', 'multi-asset')
                """
            )
        )

        migration = _load_migration()
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()

        rows = dict(
            connection.execute(
                text("SELECT id, result_version_id FROM ingest_tasks ORDER BY id")
            ).all()
        )
        assert rows["single-task"] == "single-v1"
        assert rows["multi-task"] is None

        migration.downgrade()
        columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(ingest_tasks)")).all()
        }
        assert "result_version_id" not in columns

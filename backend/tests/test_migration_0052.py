from __future__ import annotations

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0052_naming_rule_center.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0052", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0052_upgrade_and_downgrade_naming_rule_schema():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id CHAR(32) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE projects (id CHAR(32) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE knowledge_assets (id CHAR(32) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE knowledge_asset_versions (id CHAR(32) PRIMARY KEY)"))
        migration = _load_migration()
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()
        inspector = inspect(connection)
        assert "naming_rule_revisions" in inspector.get_table_names()
        assert {column["name"] for column in inspector.get_columns("projects")} >= {
            "project_code",
            "project_code_active",
            "naming_default_confidentiality",
        }
        assert {column["name"] for column in inspector.get_columns("knowledge_assets")} >= {
            "canonical_name"
        }
        assert {column["name"] for column in inspector.get_columns("knowledge_asset_versions")} >= {
            "naming_metadata",
            "naming_rule_version",
        }
        revisions = connection.execute(
            text(
                "SELECT version, status, base_published_version "
                "FROM naming_rule_revisions ORDER BY version"
            )
        ).all()
        assert revisions == [(1, "published", 0), (2, "draft", 1)]

        migration.downgrade()
        inspector = inspect(connection)
        assert "naming_rule_revisions" not in inspector.get_table_names()
        assert "project_code" not in {
            column["name"] for column in inspector.get_columns("projects")
        }

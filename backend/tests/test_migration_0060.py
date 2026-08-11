from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0060_naming_category_asset_type.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0060", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0060_backfills_known_categories_and_reports_unknown_categories():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE naming_rule_revisions (id INTEGER PRIMARY KEY, config JSON)")
        )
        connection.execute(
            text("INSERT INTO naming_rule_revisions (id, config) VALUES (1, :config)"),
            {
                "config": json.dumps(
                    {
                        "schema_version": 1,
                        "categories": [
                            {"id": "known", "secondary": "交付成果", "enabled": True},
                            {"id": "unknown", "secondary": "项目复盘", "enabled": True},
                            {"id": "disabled", "secondary": "自定义", "enabled": False},
                        ],
                    },
                    ensure_ascii=False,
                )
            },
        )
        migration = _load_migration()
        migration.op = Operations(MigrationContext.configure(connection))

        migration.upgrade()
        raw = connection.execute(
            text("SELECT config FROM naming_rule_revisions WHERE id = 1")
        ).scalar_one()
        config = json.loads(raw) if isinstance(raw, str) else raw
        assert config["schema_version"] == 2
        assert config["categories"][0]["asset_type"] == "deliverable"
        assert config["categories"][1]["asset_type"] is None
        assert config["migration_missing_asset_type_category_ids"] == ["unknown"]

        migration.downgrade()
        raw = connection.execute(
            text("SELECT config FROM naming_rule_revisions WHERE id = 1")
        ).scalar_one()
        downgraded = json.loads(raw) if isinstance(raw, str) else raw
        assert downgraded["schema_version"] == 1
        assert all("asset_type" not in item for item in downgraded["categories"])
        assert "migration_missing_asset_type_category_ids" not in downgraded

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from app.services.directories import default_directory_config


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0071_backfill_directory_rule_defaults.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0071", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _legacy_directories() -> list[dict]:
    return [
        {
            key: value
            for key, value in directory.items()
            if key not in {"naming_code", "default_confidentiality"}
        }
        for directory in default_directory_config()
    ]


def _read_config(connection, rule_id: int) -> dict:
    raw = connection.execute(
        text("SELECT config FROM naming_rule_revisions WHERE id = :id"), {"id": rule_id}
    ).scalar_one()
    return json.loads(raw) if isinstance(raw, str) else raw


def test_0071_repairs_all_historical_directory_revisions_idempotently():
    engine = create_engine("sqlite://")
    legacy_directories = _legacy_directories()
    # Historical JSON can contain blank placeholders as well as absent keys.
    legacy_directories[1]["naming_code"] = "  "
    legacy_directories[1]["default_confidentiality"] = ""
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE naming_rule_revisions "
                "(id INTEGER PRIMARY KEY, status VARCHAR(20), config JSON)"
            )
        )
        migration = _load_migration()
        migration.op = Operations(MigrationContext.configure(connection))
        # Empty production databases may have the table but no rule revisions yet.
        migration.upgrade()
        for rule_id, status in ((1, "published"), (2, "draft")):
            connection.execute(
                text(
                    "INSERT INTO naming_rule_revisions (id, status, config) "
                    "VALUES (:id, :status, :config)"
                ),
                {
                    "id": rule_id,
                    "status": status,
                    "config": json.dumps(
                        {
                            "schema_version": 2,
                            "directories": legacy_directories,
                            "custom_history": {"keep": True},
                        },
                        ensure_ascii=False,
                    ),
                },
            )
        connection.execute(
            text(
                "INSERT INTO naming_rule_revisions (id, status, config) "
                "VALUES (3, 'published', :config)"
            ),
            {
                "config": json.dumps(
                    {
                        "directories": [
                            {
                                **legacy_directories[0],
                                "naming_code": "保留短码",
                                "default_confidentiality": "L5",
                                "custom_field": "unchanged",
                            }
                        ]
                    },
                    ensure_ascii=False,
                )
            },
        )
        connection.execute(
            text(
                "INSERT INTO naming_rule_revisions (id, status, config) "
                "VALUES (4, 'draft', :config)"
            ),
            {"config": json.dumps({"schema_version": 2, "directories": []})},
        )
        connection.execute(
            text(
                "INSERT INTO naming_rule_revisions (id, status, config) "
                "VALUES (5, 'draft', :config)"
            ),
            {"config": json.dumps({"schema_version": 2})},
        )

        migration.upgrade()
        first_pass = [_read_config(connection, rule_id) for rule_id in range(1, 6)]
        migration.upgrade()
        second_pass = [_read_config(connection, rule_id) for rule_id in range(1, 6)]

        assert second_pass == first_pass
        for config in first_pass[:2]:
            directories = config["directories"]
            assert len(directories) == 17
            assert [item["directory_key"] for item in directories] == [
                item["directory_key"] for item in legacy_directories
            ]
            assert [item["naming_code"] for item in directories] == [
                item["display_name"].split(" ", maxsplit=1)[1] for item in legacy_directories
            ]
            assert all(item["default_confidentiality"] == "L2" for item in directories)
            assert config["custom_history"] == {"keep": True}

        preserved = first_pass[2]["directories"][0]
        assert preserved["naming_code"] == "保留短码"
        assert preserved["default_confidentiality"] == "L5"
        assert preserved["custom_field"] == "unchanged"
        assert first_pass[3]["directories"] == []
        assert "directories" not in first_pass[4]

        migration.downgrade()
        assert [_read_config(connection, rule_id) for rule_id in range(1, 6)] == first_pass

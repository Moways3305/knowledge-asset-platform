"""Backfill required defaults in historical governed-directory configurations.

Revision ID: 0071_backfill_directory_rule_defaults
Revises: 0070_workbuddy_remote_mcp

``0061_governed_directories`` introduced the directory rows before
``naming_code`` and ``default_confidentiality`` became required API fields.
Published revisions are immutable application data, so repair their JSON in
place without creating, deleting, or renumbering rule revisions.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

import sqlalchemy as sa

from alembic import op

revision = "0071_backfill_directory_rule_defaults"
down_revision = "0070_workbuddy_remote_mcp"
branch_labels = None
depends_on = None

_DISPLAY_ORDER_PREFIX = re.compile(r"^\s*\d{1,2}\s+")


def _decode_config(raw: object) -> dict[str, object] | None:
    """Return a mutable config mapping without treating malformed data as empty."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    return dict(raw) if isinstance(raw, Mapping) else None


def _missing(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _default_naming_code(display_name: object) -> str | None:
    if not isinstance(display_name, str):
        return None
    normalized = " ".join(display_name.strip().split())
    if not normalized:
        return None
    without_order = _DISPLAY_ORDER_PREFIX.sub("", normalized).strip()
    return without_order or normalized


def _repair_config(raw: object) -> tuple[dict[str, object] | None, bool]:
    """Fill only missing required directory fields and preserve all other JSON."""
    config = _decode_config(raw)
    if config is None:
        return None, False
    directories = config.get("directories")
    if not isinstance(directories, list):
        return config, False

    repaired_directories: list[object] = []
    changed = False
    for raw_directory in directories:
        if not isinstance(raw_directory, Mapping):
            repaired_directories.append(raw_directory)
            continue

        directory = dict(raw_directory)
        if _missing(directory.get("naming_code")):
            naming_code = _default_naming_code(directory.get("display_name"))
            if naming_code is not None:
                directory["naming_code"] = naming_code
                changed = True
        if _missing(directory.get("default_confidentiality")):
            directory["default_confidentiality"] = "L2"
            changed = True
        repaired_directories.append(directory)

    if changed:
        # Replacing the list preserves its original directory order exactly.
        config["directories"] = repaired_directories
    return config, changed


def upgrade() -> None:
    connection = op.get_bind()
    # Reflect the existing column type so binding works for both JSON and JSONB
    # deployments instead of coercing a JSONB column through a text value.
    columns = {
        column["name"]: column["type"]
        for column in sa.inspect(connection).get_columns("naming_rule_revisions")
    }
    config_type = columns["config"]
    rows = connection.execute(sa.text("SELECT id, config FROM naming_rule_revisions")).mappings()
    update = sa.text("UPDATE naming_rule_revisions SET config = :config WHERE id = :id").bindparams(
        sa.bindparam("config", type_=config_type)
    )
    for row in rows:
        config, changed = _repair_config(row["config"])
        if changed and config is not None:
            connection.execute(update, {"id": row["id"], "config": config})


def downgrade() -> None:
    # This is an additive production data repair. Removing the values could erase
    # directory settings that an operator edited after the upgrade.
    pass

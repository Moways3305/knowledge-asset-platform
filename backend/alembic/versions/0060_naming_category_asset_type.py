"""backfill explicit naming category asset classifications

Revision ID: 0060_naming_category_asset_type
Revises: 0059_canonical_markdown_derivatives
Create Date: 2026-08-11
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0060_naming_category_asset_type"
down_revision: str | None = "0059_canonical_markdown_derivatives"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEGACY_ASSET_TYPES = {
    "交付成果": "deliverable",
    "交付件": "deliverable",
    "年度计划": "deliverable",
    "制度规范": "deliverable",
    "辅导过程": "deliverable",
    "模型工具": "methodology",
    "方法论": "methodology",
    "案例研究": "case",
    "案例": "case",
    "模板": "template",
    "研究洞察": "insight",
    "洞察": "insight",
}


def _config_dict(raw: object) -> dict:
    if isinstance(raw, str):
        decoded = json.loads(raw)
        return dict(decoded) if isinstance(decoded, dict) else {}
    return dict(raw) if isinstance(raw, dict) else {}


def upgrade() -> None:
    connection = op.get_bind()
    revisions = connection.execute(
        sa.text("SELECT id, config FROM naming_rule_revisions")
    ).mappings()
    for revision_row in revisions:
        config = _config_dict(revision_row["config"])
        categories = []
        missing_ids: list[str] = []
        for raw_category in config.get("categories") or []:
            category = dict(raw_category)
            if not category.get("asset_type"):
                category["asset_type"] = _LEGACY_ASSET_TYPES.get(
                    str(category.get("secondary") or "").strip()
                )
            if category.get("enabled", True) and not category.get("asset_type"):
                missing_ids.append(str(category.get("id")))
            categories.append(category)
        config["schema_version"] = 2
        config["categories"] = categories
        config["migration_missing_asset_type_category_ids"] = missing_ids
        connection.execute(
            sa.text("UPDATE naming_rule_revisions SET config = :config WHERE id = :id").bindparams(
                sa.bindparam("config", type_=sa.JSON())
            ),
            {"config": config, "id": revision_row["id"]},
        )


def downgrade() -> None:
    connection = op.get_bind()
    revisions = connection.execute(
        sa.text("SELECT id, config FROM naming_rule_revisions")
    ).mappings()
    for revision_row in revisions:
        config = _config_dict(revision_row["config"])
        categories = []
        for raw_category in config.get("categories") or []:
            category = dict(raw_category)
            category.pop("asset_type", None)
            categories.append(category)
        config["schema_version"] = 1
        config["categories"] = categories
        config.pop("migration_missing_asset_type_category_ids", None)
        connection.execute(
            sa.text("UPDATE naming_rule_revisions SET config = :config WHERE id = :id").bindparams(
                sa.bindparam("config", type_=sa.JSON())
            ),
            {"config": config, "id": revision_row["id"]},
        )

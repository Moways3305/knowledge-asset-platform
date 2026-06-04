"""weknora_kb_mapping_and_version_cols

R1 WeKnora 底座接入：建 weknora_kb_mappings 表 + 给 knowledge_asset_versions 加
weknora_kb_id / weknora_doc_id / weknora_parse_status 列。不动其它表、不加 chunk 列。

Revision ID: 0011_weknora
Revises: 0010_ingest_extract
Create Date: 2026-05-31

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_weknora"
down_revision: str | None = "0010_ingest_extract"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "weknora_kb_mappings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("weknora_kb_id", sa.String(length=128), nullable=False),
        sa.Column("embedding_model_id", sa.String(length=128), nullable=True),
        sa.Column("kb_name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope", "owner_user_id", "project_id", name="uq_weknora_kb_scope_entity"
        ),
    )
    op.add_column(
        "knowledge_asset_versions",
        sa.Column("weknora_kb_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "knowledge_asset_versions",
        sa.Column("weknora_doc_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "knowledge_asset_versions",
        sa.Column("weknora_parse_status", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_asset_versions", "weknora_parse_status")
    op.drop_column("knowledge_asset_versions", "weknora_doc_id")
    op.drop_column("knowledge_asset_versions", "weknora_kb_id")
    op.drop_table("weknora_kb_mappings")

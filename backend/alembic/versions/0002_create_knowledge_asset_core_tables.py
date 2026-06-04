"""create_knowledge_asset_core_tables

建立知识资产核心 6 张表：
knowledge_assets / knowledge_asset_versions / knowledge_asset_chunks /
knowledge_asset_file_objects / knowledge_asset_summaries / knowledge_asset_tags。

不创建权限、入库、审核、审计、预览、Agent 等后续业务表（留待后续任务）。
current_version_id 仅为普通 UUID 列（不建 DB 级外键），以规避 assets<->versions
循环外键在 SQLite 迁移上的复杂度，其一致性由服务层维护。

Revision ID: 0002_knowledge
Revises: 0001_identity
Create Date: 2026-05-29

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002_knowledge"
down_revision: str | None = "0001_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("zone", sa.String(length=20), nullable=False),
        sa.Column("asset_type", sa.String(length=30), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("maintainer_user_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("source_asset_id", sa.Uuid(), nullable=True),
        # current_version_id：普通 UUID 列，无 DB 级外键（见模块说明）。
        sa.Column("current_version_id", sa.Uuid(), nullable=True),
        sa.Column("visibility", sa.String(length=20), nullable=False),
        sa.Column("confidentiality_level", sa.String(length=2), nullable=False),
        sa.Column("ai_access_level", sa.String(length=2), nullable=False),
        sa.Column("asset_status", sa.String(length=20), nullable=False),
        sa.Column("lifecycle_route_key", sa.String(length=20), nullable=True),
        sa.Column("lifecycle_phase_key", sa.String(length=50), nullable=True),
        sa.Column("last_called_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archive_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["maintainer_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["source_asset_id"], ["knowledge_assets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "knowledge_asset_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("version_no", sa.String(length=20), nullable=False),
        sa.Column("version_status", sa.String(length=20), nullable=False),
        sa.Column("file_hash", sa.String(length=128), nullable=True),
        sa.Column("version_hash", sa.String(length=128), nullable=True),
        sa.Column("source_hash", sa.String(length=128), nullable=True),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("supersedes_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["knowledge_assets.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["supersedes_version_id"], ["knowledge_asset_versions.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", "version_no", name="uq_asset_version_no"),
    )

    # 同一资产至多一个 active 版本：部分唯一索引（PostgreSQL / SQLite 均支持 WHERE）。
    op.create_index(
        "uq_asset_one_active_version",
        "knowledge_asset_versions",
        ["asset_id"],
        unique=True,
        sqlite_where=sa.text("version_status = 'active'"),
        postgresql_where=sa.text("version_status = 'active'"),
    )

    op.create_table(
        "knowledge_asset_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_type", sa.String(length=30), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("chunk_hash", sa.String(length=128), nullable=True),
        sa.Column("chunk_status", sa.String(length=20), nullable=False),
        sa.Column("invalid_reason", sa.Text(), nullable=True),
        sa.Column("invalidated_by", sa.Uuid(), nullable=True),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_chunk_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["knowledge_assets.id"]),
        sa.ForeignKeyConstraint(["version_id"], ["knowledge_asset_versions.id"]),
        sa.ForeignKeyConstraint(["invalidated_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["replaced_by_chunk_id"], ["knowledge_asset_chunks.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id", "chunk_index", name="uq_version_chunk_index"),
    )

    op.create_table(
        "knowledge_asset_file_objects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("file_variant", sa.String(length=20), nullable=False),
        sa.Column("file_name", sa.String(length=500), nullable=False),
        sa.Column("file_mime_type", sa.String(length=100), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("storage_ref", sa.String(length=1000), nullable=False),
        sa.Column("file_hash", sa.String(length=128), nullable=True),
        sa.Column("confidentiality_level", sa.String(length=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["knowledge_assets.id"]),
        sa.ForeignKeyConstraint(["version_id"], ["knowledge_asset_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "asset_id", "version_id", "file_variant", name="uq_asset_version_file_variant"
        ),
    )

    op.create_table(
        "knowledge_asset_summaries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("summary_type", sa.String(length=30), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["knowledge_assets.id"]),
        sa.ForeignKeyConstraint(["version_id"], ["knowledge_asset_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "asset_id", "version_id", "summary_type", name="uq_asset_version_summary_type"
        ),
    )

    op.create_table(
        "knowledge_asset_tags",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("tag_name", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["knowledge_assets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", "tag_name", name="uq_asset_tag_name"),
    )


def downgrade() -> None:
    op.drop_table("knowledge_asset_tags")
    op.drop_table("knowledge_asset_summaries")
    op.drop_table("knowledge_asset_file_objects")
    op.drop_table("knowledge_asset_chunks")
    op.drop_index("uq_asset_one_active_version", table_name="knowledge_asset_versions")
    op.drop_table("knowledge_asset_versions")
    op.drop_table("knowledge_assets")

"""add naming rule revisions and canonical naming snapshots

Revision ID: 0052_naming_rule_center
Revises: 0051_upload_sessions
Create Date: 2026-08-02
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone

import sqlalchemy as sa

from alembic import op

revision: str = "0052_naming_rule_center"
down_revision: str | None = "0051_upload_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("project_code", sa.String(length=20), nullable=True))
        batch.add_column(
            sa.Column(
                "project_code_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column(
                "naming_default_confidentiality",
                sa.String(length=2),
                nullable=False,
                server_default="L2",
            )
        )
        batch.create_unique_constraint("uq_projects_project_code", ["project_code"])

    with op.batch_alter_table("knowledge_assets") as batch:
        batch.add_column(sa.Column("canonical_name", sa.String(length=500), nullable=True))
    with op.batch_alter_table("knowledge_asset_versions") as batch:
        batch.add_column(sa.Column("naming_metadata", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("naming_rule_version", sa.Integer(), nullable=True))

    op.create_table(
        "naming_rule_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("base_published_version", sa.Integer(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("published_by", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["published_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version"),
    )
    op.create_index(
        "uq_naming_rule_single_draft",
        "naming_rule_revisions",
        ["status"],
        unique=True,
        sqlite_where=sa.text("status = 'draft'"),
        postgresql_where=sa.text("status = 'draft'"),
    )
    op.create_index(
        "ix_naming_rule_status_version",
        "naming_rule_revisions",
        ["status", "version"],
        unique=False,
    )
    now = datetime.now(timezone.utc)
    table = sa.table(
        "naming_rule_revisions",
        sa.column("id", sa.Uuid()),
        sa.column("version", sa.Integer()),
        sa.column("status", sa.String()),
        sa.column("base_published_version", sa.Integer()),
        sa.column("config", sa.JSON()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    initial = {"schema_version": 1, "enforced": False, "project_codes": [], "categories": []}
    op.bulk_insert(
        table,
        [
            {
                "id": uuid.uuid4(),
                "version": 1,
                "status": "published",
                "base_published_version": 0,
                "config": initial,
                "created_at": now,
                "updated_at": now,
            },
            {
                "id": uuid.uuid4(),
                "version": 2,
                "status": "draft",
                "base_published_version": 1,
                "config": initial,
                "created_at": now,
                "updated_at": now,
            },
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_naming_rule_status_version", table_name="naming_rule_revisions")
    op.drop_index("uq_naming_rule_single_draft", table_name="naming_rule_revisions")
    op.drop_table("naming_rule_revisions")
    with op.batch_alter_table("knowledge_asset_versions") as batch:
        batch.drop_column("naming_rule_version")
        batch.drop_column("naming_metadata")
    with op.batch_alter_table("knowledge_assets") as batch:
        batch.drop_column("canonical_name")
    with op.batch_alter_table("projects") as batch:
        batch.drop_constraint("uq_projects_project_code", type_="unique")
        batch.drop_column("naming_default_confidentiality")
        batch.drop_column("project_code_active")
        batch.drop_column("project_code")

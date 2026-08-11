"""Add controlled canonical Markdown derivatives.

Revision ID: 0059_canonical_markdown_derivatives
Revises: 0058_ingest_suggested_formed_on
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0059_canonical_markdown_derivatives"
down_revision: str | None = "0058_ingest_suggested_formed_on"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingest_task_derivatives",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ingest_task_id", sa.Uuid(), nullable=False),
        sa.Column("derivative_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("format_version", sa.String(length=30), nullable=False),
        sa.Column("source_content_hash", sa.String(length=64), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("storage_ref", sa.String(length=1000), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("linked_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["ingest_task_id"], ["ingest_tasks.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["linked_version_id"], ["knowledge_asset_versions.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ingest_task_id", "derivative_type", name="uq_ingest_task_derivative_type"
        ),
    )
    op.create_index(
        "ix_ingest_task_derivatives_ingest_task_id",
        "ingest_task_derivatives",
        ["ingest_task_id"],
    )
    op.create_index(
        "ix_ingest_task_derivatives_linked_version_id",
        "ingest_task_derivatives",
        ["linked_version_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ingest_task_derivatives_linked_version_id", table_name="ingest_task_derivatives"
    )
    op.drop_index(
        "ix_ingest_task_derivatives_ingest_task_id", table_name="ingest_task_derivatives"
    )
    op.drop_table("ingest_task_derivatives")

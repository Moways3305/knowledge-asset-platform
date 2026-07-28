"""wecom project scan spaces

Revision ID: 0046_wecom_project_scan_spaces
Revises: 0045_project_archived_status
Create Date: 2026-07-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0046_wecom_project_scan_spaces"
down_revision: str | None = "0045_project_archived_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wecom_project_scan_spaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("space_id", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("manager_access_status", sa.String(length=40), nullable=False),
        sa.Column("manager_count", sa.Integer(), nullable=False),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_wecom_project_scan_space_project"),
    )


def downgrade() -> None:
    op.drop_table("wecom_project_scan_spaces")

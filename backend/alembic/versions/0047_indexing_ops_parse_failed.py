"""add parse failure count to indexing operations snapshots

Revision ID: 0047_indexing_ops_parse_failed
Revises: 0046_wecom_project_scan_spaces
Create Date: 2026-07-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0047_indexing_ops_parse_failed"
down_revision: str | None = "0046_wecom_project_scan_spaces"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("indexing_ops_snapshots") as batch_op:
        batch_op.add_column(
            sa.Column("parse_failed", sa.Integer(), server_default="0", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("indexing_ops_snapshots") as batch_op:
        batch_op.drop_column("parse_failed")

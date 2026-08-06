"""Add KB migration state to weknora_kb_mappings.

Revision ID: 0056_weknora_kb_migration_state
Revises: 0055_ops_reconcile_heartbeat
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0056_weknora_kb_migration_state"
down_revision: str | None = "0055_ops_reconcile_heartbeat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "weknora_kb_mappings",
        sa.Column("migration_state", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("weknora_kb_mappings", "migration_state")

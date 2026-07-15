"""add safe ingest processing stage marker (PBC-69)

Revision ID: 0040_ingest_processing_stage
Revises: 0039_business_governance_boundaries
Create Date: 2026-07-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0040_ingest_processing_stage"
down_revision: str | None = "0039_business_governance_boundaries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ingest_tasks",
        sa.Column("processing_stage", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ingest_tasks", "processing_stage")

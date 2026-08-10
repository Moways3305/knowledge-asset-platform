"""Add suggested_formed_on to ingest_tasks.

Revision ID: 0058_ingest_suggested_formed_on
Revises: 0057_chunk_source_page_section
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0058_ingest_suggested_formed_on"
down_revision: str | None = "0057_chunk_source_page_section"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ingest_tasks",
        sa.Column("suggested_formed_on", sa.String(length=10), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ingest_tasks", "suggested_formed_on")

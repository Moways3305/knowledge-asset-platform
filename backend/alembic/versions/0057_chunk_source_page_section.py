"""Add source page/section to knowledge_asset_chunks.

Revision ID: 0057_chunk_source_page_section
Revises: 0056_weknora_kb_migration_state
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0057_chunk_source_page_section"
down_revision: str | None = "0056_weknora_kb_migration_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("knowledge_asset_chunks", sa.Column("source_page", sa.Integer(), nullable=True))
    op.add_column(
        "knowledge_asset_chunks", sa.Column("source_section", sa.String(length=200), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("knowledge_asset_chunks", "source_section")
    op.drop_column("knowledge_asset_chunks", "source_page")

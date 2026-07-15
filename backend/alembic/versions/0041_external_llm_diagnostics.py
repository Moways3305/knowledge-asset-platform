"""add safe external LLM connection diagnostics

Revision ID: 0041_external_llm_diagnostics
Revises: 0040_ingest_processing_stage
Create Date: 2026-07-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0041_external_llm_diagnostics"
down_revision: str | None = "0040_ingest_processing_stage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "content_generation_models",
        sa.Column("last_test_succeeded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "content_generation_models",
        sa.Column("last_test_failed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "content_generation_models",
        sa.Column("last_error_category", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("content_generation_models", "last_error_category")
    op.drop_column("content_generation_models", "last_test_failed_at")
    op.drop_column("content_generation_models", "last_test_succeeded_at")

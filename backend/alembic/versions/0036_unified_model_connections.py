"""map encrypted model connections to capabilities and WeKnora adapters

Revision ID: 0036_unified_model_connections
Revises: 0035_content_generation_models
Create Date: 2026-07-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0036_unified_model_connections"
down_revision: str | None = "0035_content_generation_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "content_generation_models",
        sa.Column("capability_type", sa.String(length=20), nullable=False, server_default="chat"),
    )
    op.add_column(
        "content_generation_models",
        sa.Column("weknora_model_ref", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_content_generation_models_weknora_model_ref",
        "content_generation_models",
        ["weknora_model_ref"],
        unique=True,
    )
    op.alter_column("content_generation_models", "capability_type", server_default=None)


def downgrade() -> None:
    op.drop_index(
        "ix_content_generation_models_weknora_model_ref",
        table_name="content_generation_models",
    )
    op.drop_column("content_generation_models", "weknora_model_ref")
    op.drop_column("content_generation_models", "capability_type")

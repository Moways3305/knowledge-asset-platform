"""weknora default models singleton (PBC-38)

Revision ID: 0033_weknora_default_models
Revises: 0032_agent_token_rotated_at
Create Date: 2026-06-25

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033_weknora_default_models"
down_revision: str | None = "0032_agent_token_rotated_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "weknora_default_models",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("default_embedding_model_id", sa.String(length=128), nullable=True),
        sa.Column("default_rerank_model_id", sa.String(length=128), nullable=True),
        sa.Column("default_chat_model_id", sa.String(length=128), nullable=True),
        sa.Column("default_multimodal_model_id", sa.String(length=128), nullable=True),
        sa.Column("updated_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("weknora_default_models")

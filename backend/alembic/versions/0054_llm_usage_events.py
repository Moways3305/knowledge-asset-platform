"""Add safe LLM usage events.

Revision ID: 0054_llm_usage_events
Revises: 0053_ingest_naming_advice_sources
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0054_llm_usage_events"
down_revision: str | None = "0053_ingest_naming_advice_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_usage_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scenario", sa.String(length=40), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("model_ref", sa.String(length=24), nullable=False),
        sa.Column("batch_size", sa.Integer(), nullable=False),
        sa.Column("cache_status", sa.String(length=16), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_usage_events_scenario", "llm_usage_events", ["scenario"])
    op.create_index("ix_llm_usage_events_created_at", "llm_usage_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_usage_events_created_at", table_name="llm_usage_events")
    op.drop_index("ix_llm_usage_events_scenario", table_name="llm_usage_events")
    op.drop_table("llm_usage_events")

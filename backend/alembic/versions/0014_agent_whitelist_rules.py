"""agent_whitelist_rules

R4 Dify 接入注册：建 agent_whitelist_rules 表（Dify Bearer 鉴权 + provider 抽象 +
capability 边界）。只存 token_hash（绝不存明文 token）；不动其它表。

Revision ID: 0014_agent_whitelist
Revises: 0013_agent_chunk_refs
Create Date: 2026-06-01

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_agent_whitelist"
down_revision: str | None = "0013_agent_chunk_refs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_whitelist_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("agent_identifier", sa.String(length=200), nullable=False),
        sa.Column("agent_name", sa.String(length=200), nullable=False),
        sa.Column("capability", sa.String(length=30), nullable=False),
        sa.Column("allowed_scope", sa.String(length=100), nullable=True),
        sa.Column("allowed_project_id", sa.Uuid(), nullable=True),
        sa.Column("max_confidentiality_level", sa.String(length=2), nullable=False),
        sa.Column("max_ai_access_level", sa.String(length=2), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("risk_level", sa.String(length=20), nullable=True),
        sa.Column("risk_note", sa.Text(), nullable=True),
        sa.Column("external_app_id", sa.String(length=200), nullable=True),
        sa.Column("external_workflow_id", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["allowed_project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_identifier", name="uq_agent_whitelist_identifier"),
        sa.UniqueConstraint("token_hash", name="uq_agent_whitelist_token_hash"),
    )


def downgrade() -> None:
    op.drop_table("agent_whitelist_rules")

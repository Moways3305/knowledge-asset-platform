"""Add expiry and mode for short-lived WorkBuddy remote MCP credentials.

Revision ID: 0070_workbuddy_remote_mcp
Revises: 0069_ocr_queue_recovery
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0070_workbuddy_remote_mcp"
down_revision = "0069_ocr_queue_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_whitelist_rules",
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "agent_whitelist_rules",
        sa.Column("workbuddy_connection_mode", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_agent_whitelist_rules_token_expires_at",
        "agent_whitelist_rules",
        ["token_expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_whitelist_rules_token_expires_at",
        table_name="agent_whitelist_rules",
    )
    op.drop_column("agent_whitelist_rules", "workbuddy_connection_mode")
    op.drop_column("agent_whitelist_rules", "token_expires_at")

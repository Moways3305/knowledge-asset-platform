"""Persistent, restart-safe MCP OAuth state."""

import sqlalchemy as sa

from alembic import op

revision = "0078_mcp_oauth"
down_revision = "0077_knowledge_version_updates"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "agent_whitelist_rules",
        sa.Column("is_mcp_oauth_grant", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "mcp_oauth_records",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_mcp_oauth_records_kind", "mcp_oauth_records", ["kind"])
    op.create_index("ix_mcp_oauth_records_expires_at", "mcp_oauth_records", ["expires_at"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM mcp_oauth_records")):
        raise RuntimeError("Revoke and preserve OAuth grants before downgrading")
    op.drop_table("mcp_oauth_records")
    op.drop_column("agent_whitelist_rules", "is_mcp_oauth_grant")

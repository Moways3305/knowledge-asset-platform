"""Persist scan scope and per-run outcomes without modifying knowledge content."""

import sqlalchemy as sa
from alembic import op

revision = "0090_maintenance_run_details"
down_revision = "0089_maintenance_agent"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("maintenance_agent_runs", sa.Column("scope_snapshot", sa.JSON(), nullable=True))
    op.create_table(
        "maintenance_agent_run_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("maintenance_agent_runs.id"), nullable=False),
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("knowledge_assets.id"), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("coverage", sa.JSON(), nullable=False),
        sa.Column("findings", sa.JSON(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id", "asset_id", name="uq_maintenance_run_asset"),
    )


def downgrade():
    op.drop_table("maintenance_agent_run_items")
    op.drop_column("maintenance_agent_runs", "scope_snapshot")

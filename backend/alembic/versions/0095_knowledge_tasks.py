"""Private delegated knowledge tasks."""

import sqlalchemy as sa
from alembic import op

revision = "0095_knowledge_tasks"
down_revision = "0094_maintenance_continuity"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "knowledge_agent_tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("library_key", sa.String(60), nullable=False),
        sa.Column("instruction", sa.String(600), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("claim", sa.Uuid()),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_knowledge_tasks_owner",
        "knowledge_agent_tasks",
        ["user_id", "role", "library_key", "created_at"],
    )
    op.create_index(
        "ix_knowledge_tasks_recovery", "knowledge_agent_tasks", ["status", "lease_until"]
    )


def downgrade():
    op.drop_table("knowledge_agent_tasks")

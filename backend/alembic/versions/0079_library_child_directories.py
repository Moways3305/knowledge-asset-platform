"""Add library-scoped child directories without publishing global drafts."""

import sqlalchemy as sa

from alembic import op

revision = "0079_library_child_directories"
down_revision = "0078_mcp_oauth"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "knowledge_directories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("directory_key", sa.String(100), nullable=False, unique=True),
        sa.Column("library_key", sa.String(50), nullable=False),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id")),
        sa.Column("parent_key", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("normalized_name", sa.String(80), nullable=False),
        sa.Column("default_confidentiality", sa.String(10), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("library_key", "parent_key", "normalized_name"),
    )


def downgrade():
    op.drop_table("knowledge_directories")

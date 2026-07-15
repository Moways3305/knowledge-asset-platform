"""business governance boundaries and company asset dual confirmation (PBC-66)

Revision ID: 0039_business_governance_boundaries
Revises: 0038_project_qa_model_ref
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0039_business_governance_boundaries"
down_revision: str | None = "0038_project_qa_model_ref"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "company_asset_review_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("review_task_id", sa.Uuid(), nullable=False),
        sa.Column("required_role", sa.String(length=40), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["review_task_id"], ["review_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_company_asset_review_decisions_task_role_created",
        "company_asset_review_decisions",
        ["review_task_id", "required_role", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_company_asset_review_decisions_task_role_created",
        table_name="company_asset_review_decisions",
    )
    op.drop_table("company_asset_review_decisions")

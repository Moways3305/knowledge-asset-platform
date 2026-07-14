"""add project ingest approval state

Revision ID: 0037_project_ingest_approval
Revises: 0036_unified_model_connections
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0037_project_ingest_approval"
down_revision: str | None = "0036_unified_model_connections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "review_tasks",
        "target_asset_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )
    op.add_column("review_tasks", sa.Column("source_ingest_task_id", sa.Uuid(), nullable=True))
    op.add_column("review_tasks", sa.Column("confirmation_snapshot", sa.JSON(), nullable=True))
    op.create_foreign_key(
        "fk_review_tasks_source_ingest",
        "review_tasks",
        "ingest_tasks",
        ["source_ingest_task_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_review_tasks_source_ingest", "review_tasks", ["source_ingest_task_id"]
    )


def downgrade() -> None:
    # These rows cannot satisfy the legacy non-null target_asset_id contract.
    op.execute("DELETE FROM review_tasks WHERE review_type = 'project_ingest_approval'")
    op.drop_constraint("uq_review_tasks_source_ingest", "review_tasks", type_="unique")
    op.drop_constraint("fk_review_tasks_source_ingest", "review_tasks", type_="foreignkey")
    op.drop_column("review_tasks", "confirmation_snapshot")
    op.drop_column("review_tasks", "source_ingest_task_id")
    op.alter_column(
        "review_tasks",
        "target_asset_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )

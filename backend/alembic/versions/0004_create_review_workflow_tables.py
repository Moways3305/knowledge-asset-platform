"""create_review_workflow_tables

建立审核流三张表：validation_evidences / review_tasks / review_task_evidences
（IMPLEMENT-06，仅 material_to_asset 最小闭环）。不创建原文授权/审计/预览/Agent/
生命周期/通知等后续业务表。

Revision ID: 0004_review
Revises: 0003_ingest
Create Date: 2026-05-29

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_review"
down_revision: str | None = "0003_ingest"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "validation_evidences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("evidence_type", sa.String(length=30), nullable=False),
        sa.Column("evidence_category", sa.String(length=30), nullable=False),
        sa.Column("related_asset_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("submitted_by", sa.Uuid(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("attachments", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["related_asset_id"], ["knowledge_assets.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["submitted_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_validation_evidences_asset_created",
        "validation_evidences",
        ["related_asset_id", "created_at"],
    )

    op.create_table(
        "review_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("review_type", sa.String(length=30), nullable=False),
        sa.Column("trigger_source", sa.String(length=50), nullable=False),
        sa.Column("target_asset_id", sa.Uuid(), nullable=False),
        sa.Column("target_project_id", sa.Uuid(), nullable=True),
        sa.Column("target_scope", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("reviewer_user_id", sa.Uuid(), nullable=True),
        sa.Column("submitted_by", sa.Uuid(), nullable=True),
        sa.Column("review_comment", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["target_asset_id"], ["knowledge_assets.id"]),
        sa.ForeignKeyConstraint(["target_project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["submitted_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_tasks_type_status", "review_tasks", ["review_type", "status"])
    op.create_index(
        "ix_review_tasks_reviewer_status", "review_tasks", ["reviewer_user_id", "status"]
    )

    op.create_table(
        "review_task_evidences",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("review_task_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["review_task_id"], ["review_tasks.id"]),
        sa.ForeignKeyConstraint(["evidence_id"], ["validation_evidences.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_task_id", "evidence_id", name="uq_review_evidence"),
    )


def downgrade() -> None:
    op.drop_table("review_task_evidences")
    op.drop_index("ix_review_tasks_reviewer_status", table_name="review_tasks")
    op.drop_index("ix_review_tasks_type_status", table_name="review_tasks")
    op.drop_table("review_tasks")
    op.drop_index("ix_validation_evidences_asset_created", table_name="validation_evidences")
    op.drop_table("validation_evidences")

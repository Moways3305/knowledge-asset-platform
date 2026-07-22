"""personal_knowledge_submissions

PBC-05 个人知识写动作：建 personal_knowledge_submissions 表（提交到项目 /
内部分享候选 / 客户验证候选）。只存安全枚举/UUID/备注，绝不存原文 / secret。
部分唯一索引保证 idempotency_key 幂等（PostgreSQL / SQLite 兼容）。

文件名用长名（可读性），revision id 用短名 `0020_personal_submissions`
以适配 alembic_version.version_num 长度限制（varchar(32)）。

Revision ID: 0020_personal_submissions
Revises: 0019_project_settings
Create Date: 2026-06-02

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020_personal_submissions"
down_revision: str | None = "0019_project_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "personal_knowledge_submissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("submitter_user_id", sa.Uuid(), nullable=False),
        sa.Column("source_asset_id", sa.Uuid(), nullable=False),
        sa.Column("target_project_id", sa.Uuid(), nullable=True),
        sa.Column("submission_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("review_task_id", sa.Uuid(), nullable=True),
        sa.Column("evidence_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=100), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["submitter_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["source_asset_id"], ["knowledge_assets.id"]),
        sa.ForeignKeyConstraint(["target_project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["review_task_id"], ["review_tasks.id"]),
        sa.ForeignKeyConstraint(["evidence_id"], ["validation_evidences.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pks_asset_project_type",
        "personal_knowledge_submissions",
        ["source_asset_id", "target_project_id", "submission_type"],
    )
    op.create_index(
        "uq_pks_idempotency",
        "personal_knowledge_submissions",
        [
            "submitter_user_id",
            "source_asset_id",
            "submission_type",
            "target_project_id",
            "idempotency_key",
        ],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_pks_idempotency", table_name="personal_knowledge_submissions")
    op.drop_index("ix_pks_asset_project_type", table_name="personal_knowledge_submissions")
    op.drop_table("personal_knowledge_submissions")

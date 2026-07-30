"""link ingest source files to the materialized asset version

Revision ID: 0050_ingest_task_result_version
Revises: 0049_workbuddy_self_service_source
Create Date: 2026-07-30
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0050_ingest_task_result_version"
down_revision: str | None = "0049_workbuddy_self_service_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("ingest_tasks") as batch_op:
        batch_op.add_column(sa.Column("result_version_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_ingest_tasks_result_version_id_knowledge_asset_versions",
            "knowledge_asset_versions",
            ["result_version_id"],
            ["id"],
        )
        batch_op.create_index(
            "ix_ingest_tasks_result_version_id",
            ["result_version_id"],
            unique=False,
        )

    # 只有资产恰好一个版本时，历史任务与 current 版本的对应关系才可被证明。
    # 多版本资产无法从旧结构判断每个任务属于哪个版本，必须保留 NULL 并 fail closed。
    op.execute(
        sa.text(
            """
            UPDATE ingest_tasks
            SET result_version_id = (
                SELECT knowledge_assets.current_version_id
                FROM knowledge_assets
                WHERE knowledge_assets.id = ingest_tasks.result_asset_id
            )
            WHERE result_asset_id IS NOT NULL
              AND result_version_id IS NULL
              AND (
                  SELECT COUNT(*)
                  FROM knowledge_asset_versions
                  WHERE knowledge_asset_versions.asset_id = ingest_tasks.result_asset_id
              ) = 1
            """
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("ingest_tasks") as batch_op:
        batch_op.drop_index("ix_ingest_tasks_result_version_id")
        batch_op.drop_constraint(
            "fk_ingest_tasks_result_version_id_knowledge_asset_versions",
            type_="foreignkey",
        )
        batch_op.drop_column("result_version_id")

"""ingest_llm_draft_columns

R2 外部 LLM 内容处理：给 ingest_task_ai_results 加结构化草稿列。仅 ALTER 这一张表，
不动其它表、不动 WeKnora 链路。

- suggested_one_liner (Text)：一句话摘要建议
- suggested_key_points (JSON)：关键知识点建议数组
- llm_provider (String)：内容处理所用 provider（安全元数据，非密钥）
- llm_model (String)：所用 model

Revision ID: 0012_llm_draft
Revises: 0011_weknora
Create Date: 2026-05-31

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012_llm_draft"
down_revision: str | None = "0011_weknora"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ingest_task_ai_results",
        sa.Column("suggested_one_liner", sa.Text(), nullable=True),
    )
    op.add_column(
        "ingest_task_ai_results",
        sa.Column("suggested_key_points", sa.JSON(), nullable=True),
    )
    op.add_column(
        "ingest_task_ai_results",
        sa.Column("llm_provider", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "ingest_task_ai_results",
        sa.Column("llm_model", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ingest_task_ai_results", "llm_model")
    op.drop_column("ingest_task_ai_results", "llm_provider")
    op.drop_column("ingest_task_ai_results", "suggested_key_points")
    op.drop_column("ingest_task_ai_results", "suggested_one_liner")

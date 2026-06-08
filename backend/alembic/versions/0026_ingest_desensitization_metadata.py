"""ingest_desensitization_metadata

PBC-13 入库前置实体级规则脱敏：给 ingest_task_ai_results 增加安全脱敏元数据列。

新增列（仅 ingest_task_ai_results，不动其它表）：
- desensitization_status       applied | unchanged | skipped | failed（安全状态，非原文）
- desensitization_counts       类别 → 替换数量（JSON；绝不含原值）
- desensitization_error_code   脱敏失败安全错误码（无原文/无堆栈）

均为安全元数据：不含脱敏文本、原文、原始文件 ref。PostgreSQL / SQLite 兼容（仅
add_column），可逆 downgrade。SQLite 测试库由 create_all 直接建列覆盖。

Revision ID: 0026_ingest_desensitization_metadata
Revises: 0025_user_password_credentials
Create Date: 2026-06-05

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026_ingest_desensitization_metadata"
down_revision: str | None = "0025_user_password_credentials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ingest_task_ai_results",
        sa.Column("desensitization_status", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "ingest_task_ai_results",
        sa.Column("desensitization_counts", sa.JSON(), nullable=True),
    )
    op.add_column(
        "ingest_task_ai_results",
        sa.Column("desensitization_error_code", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ingest_task_ai_results", "desensitization_error_code")
    op.drop_column("ingest_task_ai_results", "desensitization_counts")
    op.drop_column("ingest_task_ai_results", "desensitization_status")

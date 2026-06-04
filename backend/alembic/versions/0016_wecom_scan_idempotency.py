"""wecom_scan_idempotency

R6_FIX：给 wecom_scan_records 的 (config_id, idempotency_key) 加**部分唯一索引**
（仅 idempotency_key 非空时唯一），DB 级保证同 config + 同 Idempotency-Key 只建一条记录。
PostgreSQL / SQLite(>=3.8) 均支持带 WHERE 的部分唯一索引，跨库可用。

Revision ID: 0016_wecom_idem
Revises: 0015_wecom
Create Date: 2026-06-01

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_wecom_idem"
down_revision: str | None = "0015_wecom"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_wecom_scan_idempotency",
        "wecom_scan_records",
        ["config_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_wecom_scan_idempotency", table_name="wecom_scan_records")

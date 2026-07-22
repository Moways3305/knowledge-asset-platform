"""preview_render_and_notify_delivery

R7：
- preview_credentials 加 fetch_token_hash（ONLYOFFICE 受控取件 token 的 sha256，server-only）。
- notification_records 加 send_attempts / failure_reason（真实下发投递元数据，安全）。
不动其它表。

Revision ID: 0017_r7_preview_notify
Revises: 0016_wecom_idem
Create Date: 2026-06-01

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017_r7_preview_notify"
down_revision: str | None = "0016_wecom_idem"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "preview_credentials",
        sa.Column("fetch_token_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "notification_records",
        sa.Column("send_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "notification_records",
        sa.Column("failure_reason", sa.String(length=100), nullable=True),
    )
    # 保留 server_default="0"（SQLite 不支持 ALTER DROP DEFAULT；DB 默认 0 与应用层 default 一致）。


def downgrade() -> None:
    op.drop_column("notification_records", "failure_reason")
    op.drop_column("notification_records", "send_attempts")
    op.drop_column("preview_credentials", "fetch_token_hash")

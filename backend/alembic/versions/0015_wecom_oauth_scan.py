"""wecom_oauth_scan

R6 企微 OAuth 身份 + Path A 微盘扫描：
- users 加 wecom_user_id（unique, nullable）——OAuth 身份解析键。
- 建 wecom_scan_configs / wecom_scan_records（仅这两表）。

不动其它表、不存任何 token / 下载 URL / file_id。

Revision ID: 0015_wecom
Revises: 0014_agent_whitelist
Create Date: 2026-06-01

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_wecom"
down_revision: str | None = "0014_agent_whitelist"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("wecom_user_id", sa.String(length=100), nullable=True))
    # 用唯一索引（CREATE UNIQUE INDEX）而非 ALTER ADD CONSTRAINT——后者 SQLite 不支持。
    # 语义等价（唯一、可空），PostgreSQL / SQLite 均可。
    op.create_index("uq_users_wecom_user_id", "users", ["wecom_user_id"], unique=True)

    op.create_table(
        "wecom_scan_configs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("directory_path", sa.String(length=1000), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("related_project_id", sa.Uuid(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("scan_frequency", sa.String(length=30), nullable=True),
        sa.Column("last_scan_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["related_project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "wecom_scan_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("config_id", sa.Uuid(), nullable=False),
        sa.Column("trace_id", sa.String(length=100), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("scan_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scan_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discovered_count", sa.Integer(), nullable=False),
        sa.Column("new_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("scan_status", sa.String(length=20), nullable=False),
        sa.Column("error_type", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["config_id"], ["wecom_scan_configs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_wecom_scan_records_config", "wecom_scan_records", ["config_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_wecom_scan_records_config", table_name="wecom_scan_records")
    op.drop_table("wecom_scan_records")
    op.drop_table("wecom_scan_configs")
    op.drop_index("uq_users_wecom_user_id", table_name="users")
    op.drop_column("users", "wecom_user_id")

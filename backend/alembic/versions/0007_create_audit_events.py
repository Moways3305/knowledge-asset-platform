"""create_audit_events

建立 audit_events 表（IMPLEMENT-09 审计日志最小闭环）。仅此一张表。
不创建 asset_lifecycle_events / alert_rules / notification_records 等后续治理表。

Revision ID: 0007_audit
Revises: 0006_agent
Create Date: 2026-05-29

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007_audit"
down_revision: str | None = "0006_agent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("log_type", sa.String(length=20), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_company_role", sa.String(length=30), nullable=True),
        sa.Column("actor_project_role", sa.String(length=30), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("before_snapshot", sa.JSON(), nullable=True),
        sa.Column("after_snapshot", sa.JSON(), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=True),
        sa.Column("is_processed", sa.Boolean(), nullable=False),
        sa.Column("processed_by", sa.Uuid(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(length=50), nullable=True),
        sa.Column("device_info", sa.String(length=500), nullable=True),
        sa.Column("login_result", sa.String(length=20), nullable=True),
        sa.Column("trace_id", sa.String(length=100), nullable=False),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["processed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_trace", "audit_events", ["trace_id"])
    op.create_index("ix_audit_events_logtype_created", "audit_events", ["log_type", "created_at"])
    op.create_index("ix_audit_events_action_created", "audit_events", ["action", "created_at"])
    op.create_index("ix_audit_events_actor", "audit_events", ["actor_user_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_actor", table_name="audit_events")
    op.drop_index("ix_audit_events_action_created", table_name="audit_events")
    op.drop_index("ix_audit_events_logtype_created", table_name="audit_events")
    op.drop_index("ix_audit_events_trace", table_name="audit_events")
    op.drop_table("audit_events")

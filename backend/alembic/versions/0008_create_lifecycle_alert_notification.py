"""create_lifecycle_alert_notification

建立生命周期治理三表（IMPLEMENT-10 最小闭环）：
asset_lifecycle_events / alert_rules / notification_records。仅此三张表。

Revision ID: 0008_lifecycle
Revises: 0007_audit
Create Date: 2026-05-30

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_lifecycle"
down_revision: str | None = "0007_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "asset_lifecycle_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("old_status", sa.String(length=20), nullable=True),
        sa.Column("new_status", sa.String(length=20), nullable=True),
        sa.Column("triggered_by", sa.String(length=30), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("review_task_id", sa.Uuid(), nullable=True),
        sa.Column("trace_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["knowledge_assets.id"]),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_asset_lifecycle_events_asset",
        "asset_lifecycle_events",
        ["asset_id", "created_at"],
    )
    op.create_index("ix_asset_lifecycle_events_trace", "asset_lifecycle_events", ["trace_id"])

    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rule_name", sa.String(length=200), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("threshold", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("threshold_unit", sa.String(length=50), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("notification_channels", sa.JSON(), nullable=False),
        sa.Column("dedup_strategy", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_name", name="uq_alert_rule_name"),
    )

    op.create_table(
        "notification_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("alert_rule_id", sa.Uuid(), nullable=True),
        sa.Column("audit_event_id", sa.Uuid(), nullable=True),
        sa.Column("recipient_user_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("send_status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["alert_rule_id"], ["alert_rules.id"]),
        sa.ForeignKeyConstraint(["audit_event_id"], ["audit_events.id"]),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notification_records_recipient",
        "notification_records",
        ["recipient_user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notification_records_recipient", table_name="notification_records")
    op.drop_table("notification_records")
    op.drop_table("alert_rules")
    op.drop_index("ix_asset_lifecycle_events_trace", table_name="asset_lifecycle_events")
    op.drop_index("ix_asset_lifecycle_events_asset", table_name="asset_lifecycle_events")
    op.drop_table("asset_lifecycle_events")

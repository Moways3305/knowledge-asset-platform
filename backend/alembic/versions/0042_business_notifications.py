"""add recipient-scoped business notifications

Revision ID: 0042_business_notifications
Revises: 0041_external_llm_diagnostics
Create Date: 2026-07-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0042_business_notifications"
down_revision: str | None = "0041_external_llm_diagnostics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "business_notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("target_kind", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("dedup_key", sa.String(length=140), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("delivery_status", sa.String(length=20), nullable=False),
        sa.Column("delivery_attempts", sa.Integer(), nullable=False),
        sa.Column("failure_code", sa.String(length=60), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "recipient_user_id",
            "dedup_key",
            name="uq_business_notification_recipient_event",
        ),
    )
    op.create_index(
        "ix_business_notifications_recipient_created",
        "business_notifications",
        ["recipient_user_id", "created_at"],
    )
    op.create_index(
        "ix_business_notifications_recipient_unread",
        "business_notifications",
        ["recipient_user_id", "read_at"],
    )
    op.create_index(
        "ix_business_notifications_delivery",
        "business_notifications",
        ["channel", "delivery_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_business_notifications_delivery", table_name="business_notifications")
    op.drop_index("ix_business_notifications_recipient_unread", table_name="business_notifications")
    op.drop_index(
        "ix_business_notifications_recipient_created", table_name="business_notifications"
    )
    op.drop_table("business_notifications")

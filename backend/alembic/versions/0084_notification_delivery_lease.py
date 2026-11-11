"""Add recoverable notification delivery claims and retry scheduling.

Drain old notification workers before upgrading or rolling this migration back.
"""

import sqlalchemy as sa

from alembic import op

revision = "0084_notification_delivery_lease"
down_revision = "0083_model_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("business_notifications", "notification_records"):
        op.add_column(table, sa.Column("delivery_token", sa.String(36), nullable=True))
        op.add_column(table, sa.Column("delivery_until", sa.DateTime(timezone=True), nullable=True))
        op.add_column(
            table, sa.Column("delivery_available_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    for table in ("business_notifications", "notification_records"):
        op.drop_column(table, "delivery_available_at")
        op.drop_column(table, "delivery_until")
        op.drop_column(table, "delivery_token")

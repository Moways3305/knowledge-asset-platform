"""Personal inbox lifecycle and preferences; business facts stay independent."""

import sqlalchemy as sa
from alembic import op

revision = "0092_notification_inbox"
down_revision = "0091_maintenance_batch_progress"
branch_labels = None
depends_on = None


def upgrade():
    for name in ("seen_at", "archived_at", "deleted_at"):
        op.add_column("business_notifications", sa.Column(name, sa.DateTime(timezone=True)))
    op.add_column(
        "business_notifications",
        sa.Column("in_app_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("business_notifications", sa.Column("delivery_digest_id", sa.Uuid()))
    op.create_index(
        "ix_business_notifications_delivery_digest_id",
        "business_notifications",
        ["delivery_digest_id"],
    )
    op.create_index(
        "ix_business_notifications_inbox",
        "business_notifications",
        ["recipient_user_id", "deleted_at", "archived_at", "created_at"],
    )
    op.create_table(
        "notification_preferences",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("categories", sa.JSON(), nullable=False),
        sa.Column("auto_archive_days", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("notification_preferences")
    op.drop_index("ix_business_notifications_inbox", "business_notifications")
    op.drop_index("ix_business_notifications_delivery_digest_id", "business_notifications")
    for name in ("delivery_digest_id", "in_app_enabled", "deleted_at", "archived_at", "seen_at"):
        op.drop_column("business_notifications", name)

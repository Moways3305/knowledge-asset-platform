"""durable domain event outbox

Revision ID: 0067_domain_event_outbox
Revises: 0066_upload_transport_safety
"""

import sqlalchemy as sa

from alembic import op

revision = "0067_domain_event_outbox"
down_revision = "0066_upload_transport_safety"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "domain_event_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("aggregate_type", sa.String(length=50), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=180), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("last_error_detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_domain_event_outbox_idempotency"),
    )
    op.create_index(
        "ix_domain_event_outbox_delivery",
        "domain_event_outbox",
        ["status", "available_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_domain_event_outbox_delivery", table_name="domain_event_outbox")
    op.drop_table("domain_event_outbox")

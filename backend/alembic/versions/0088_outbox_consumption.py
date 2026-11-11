"""Fence outbox ownership and persist atomic recipient-page progress.

Drain old outbox consumers before upgrade. Finish partial events with the new
consumer before downgrade; removing their cursor would replay local notices.
"""

import sqlalchemy as sa

from alembic import op

revision = "0088_outbox_consumption"
down_revision = "0087_original_access_scan"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("domain_event_outbox", sa.Column("claim_token", sa.String(36), nullable=True))
    op.add_column("domain_event_outbox", sa.Column("recipient_cursor", sa.Uuid(), nullable=True))


def downgrade() -> None:
    pending = op.get_bind().scalar(
        sa.text(
            "SELECT count(*) FROM domain_event_outbox "
            "WHERE recipient_cursor IS NOT NULL AND status <> 'completed'"
        )
    )
    if pending:
        raise RuntimeError("Finish partial outbox events before downgrade")
    op.drop_column("domain_event_outbox", "recipient_cursor")
    op.drop_column("domain_event_outbox", "claim_token")

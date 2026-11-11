"""Index fair original-access scan traversal; cursor uses governance_scan_runs.

Stop old auto-approval consumers before upgrade. Drain resume messages before
downgrade. Requests, grants, decisions and audits are never removed by rollback.
"""

import sqlalchemy as sa

from alembic import op

revision = "0087_original_access_scan"
down_revision = "0086_reuse_scan_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_oar_pending_scan",
        "original_access_requests",
        ["created_at", "id"],
        postgresql_where=sa.text("status = 'pending'"),
        sqlite_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM governance_scan_runs WHERE name = 'original_access'"))
    op.drop_index("ix_oar_pending_scan", table_name="original_access_requests")

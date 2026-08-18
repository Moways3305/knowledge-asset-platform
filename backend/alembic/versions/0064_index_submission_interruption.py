"""index submission interruption reconcile metrics

Revision ID: 0064_index_submission_interruption
Revises: 0063_index_recovery_evidence
"""

import sqlalchemy as sa

from alembic import op

revision = "0064_index_submission_interruption"
down_revision = "0063_index_recovery_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "indexing_ops_snapshots",
        sa.Column("parse_stalled", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "indexing_ops_snapshots",
        sa.Column("submission_interrupted", sa.Integer(), server_default="0", nullable=False),
    )
    for name in (
        "submission_scanned",
        "submission_interrupted",
        "submission_fresh_job_skipped",
        "submission_exceptions",
    ):
        op.add_column(
            "ops_reconcile_heartbeats",
            sa.Column(name, sa.Integer(), server_default="0", nullable=False),
        )


def downgrade() -> None:
    for name in reversed(
        (
            "submission_scanned",
            "submission_interrupted",
            "submission_fresh_job_skipped",
            "submission_exceptions",
        )
    ):
        op.drop_column("ops_reconcile_heartbeats", name)
    op.drop_column("indexing_ops_snapshots", "submission_interrupted")
    op.drop_column("indexing_ops_snapshots", "parse_stalled")

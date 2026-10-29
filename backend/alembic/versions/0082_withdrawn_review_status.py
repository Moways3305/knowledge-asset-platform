"""Separate proven withdrawals from business rejections without changing audit facts."""

import sqlalchemy as sa

from alembic import op

revision = "0082_withdrawn_review_status"
down_revision = "0081_chunk_identifier_search"
branch_labels = None
depends_on = None


def _correct_status(previous: str, target: str):
    # Ambiguous histories are deliberately left alone. The immutable audit log,
    # rather than a comment or asset title, proves which action ended the review.
    op.execute(
        sa.text("""
        UPDATE review_tasks
        SET status = :target
        WHERE status = :previous
          AND EXISTS (
            SELECT 1 FROM audit_events AS event
            WHERE event.target_type = 'review_task'
              AND event.target_id = review_tasks.id
              AND event.log_type = 'operation'
              AND (
                (review_tasks.review_type = 'material_to_asset' AND event.action = 'review.withdrawn')
                OR (review_tasks.review_type = 'project_to_company' AND event.action = 'review.company_confirmation_withdrawn')
              )
          )
          AND NOT EXISTS (
            SELECT 1 FROM audit_events AS decision
            WHERE decision.target_type = 'review_task'
              AND decision.target_id = review_tasks.id
              AND decision.log_type = 'operation'
              AND decision.action IN ('review.rejected', 'review.approved')
          )
    """).bindparams(previous=previous, target=target)
    )


def upgrade():
    _correct_status("rejected", "cancelled")


def downgrade():
    _correct_status("cancelled", "rejected")

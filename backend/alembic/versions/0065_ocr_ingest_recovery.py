"""OCR ingest recovery facts

Revision ID: 0065_ocr_ingest_recovery
Revises: 0064_index_submission_interruption
"""

import sqlalchemy as sa

from alembic import op

revision = "0065_ocr_ingest_recovery"
down_revision = "0064_index_submission_interruption"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ingest_task_ai_results", sa.Column("ocr_status", sa.String(24), nullable=True))
    op.add_column("ingest_task_ai_results", sa.Column("ocr_page_results", sa.JSON(), nullable=True))
    op.add_column("ingest_task_ai_results", sa.Column("ocr_confidence", sa.Float(), nullable=True))
    op.add_column(
        "ingest_task_ai_results",
        sa.Column("ocr_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ingest_task_ai_results", "ocr_attempted_at")
    op.drop_column("ingest_task_ai_results", "ocr_confidence")
    op.drop_column("ingest_task_ai_results", "ocr_page_results")
    op.drop_column("ingest_task_ai_results", "ocr_status")

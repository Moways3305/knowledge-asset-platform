"""expand project QA model reference

Revision ID: 0038_project_qa_model_ref
Revises: 0037_project_ingest_approval
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0038_project_qa_model_ref"
down_revision: str | None = "0037_project_ingest_approval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "agent_calls",
        "model_key",
        existing_type=sa.String(length=50),
        type_=sa.String(length=128),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "agent_calls",
        "model_key",
        existing_type=sa.String(length=128),
        type_=sa.String(length=50),
        existing_nullable=False,
    )

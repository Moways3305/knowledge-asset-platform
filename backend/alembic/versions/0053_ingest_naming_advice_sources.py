"""Persist version and content-confidentiality advice provenance.

Revision ID: 0053_ingest_naming_advice_sources
Revises: 0052_naming_rule_center
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0053_ingest_naming_advice_sources"
down_revision: str | None = "0052_naming_rule_center"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("ingest_task_ai_results") as batch:
        batch.add_column(sa.Column("suggested_version", sa.String(length=30), nullable=True))
        batch.add_column(sa.Column("version_source", sa.String(length=40), nullable=True))
        batch.add_column(sa.Column("version_confidence", sa.String(length=10), nullable=True))
        batch.add_column(sa.Column("version_reason", sa.String(length=300), nullable=True))
        batch.add_column(sa.Column("confidentiality_source", sa.String(length=40), nullable=True))
        batch.add_column(
            sa.Column("confidentiality_confidence", sa.String(length=10), nullable=True)
        )
        batch.add_column(sa.Column("confidentiality_reason", sa.String(length=300), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("ingest_task_ai_results") as batch:
        batch.drop_column("confidentiality_reason")
        batch.drop_column("confidentiality_confidence")
        batch.drop_column("confidentiality_source")
        batch.drop_column("version_reason")
        batch.drop_column("version_confidence")
        batch.drop_column("version_source")
        batch.drop_column("suggested_version")

"""Bind preview credentials to their issuing work identity for live access checks."""

import sqlalchemy as sa

from alembic import op

revision = "0080_preview_requester_role"
down_revision = "0079_library_child_directories"
branch_labels = None
depends_on = None


def upgrade():
    # Do not backfill a guessed role: existing short-lived capabilities must be reissued.
    op.add_column(
        "preview_credentials", sa.Column("requester_company_role", sa.String(30), nullable=True)
    )


def downgrade():
    op.drop_column("preview_credentials", "requester_company_role")

"""wecom auto provisioning identity fields (PBC-41)

Revision ID: 0034_wecom_auto_provisioning_identity
Revises: 0033_weknora_default_models
Create Date: 2026-07-07

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034_wecom_auto_provisioning_identity"
down_revision: str | None = "0033_weknora_default_models"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("wecom_corp_id", sa.String(length=100), nullable=True))
    op.add_column("users", sa.Column("wecom_name", sa.String(length=100), nullable=True))
    op.add_column("users", sa.Column("wecom_email", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("wecom_avatar", sa.String(length=500), nullable=True))
    op.add_column("users", sa.Column("wecom_department_ids", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("wecom_synced_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_index("uq_users_wecom_user_id", table_name="users")
    op.create_index(
        "uq_users_wecom_corp_userid",
        "users",
        ["wecom_corp_id", "wecom_user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_users_wecom_corp_userid", table_name="users")
    op.create_index("uq_users_wecom_user_id", "users", ["wecom_user_id"], unique=True)
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "wecom_synced_at")
    op.drop_column("users", "wecom_department_ids")
    op.drop_column("users", "wecom_avatar")
    op.drop_column("users", "wecom_email")
    op.drop_column("users", "wecom_name")
    op.drop_column("users", "wecom_corp_id")

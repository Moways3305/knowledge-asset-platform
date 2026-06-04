"""create_preview_credentials

建立 preview_credentials 表（IMPLEMENT-07 预览凭证最小闭环）。不创建 access_grants /
original_access_requests / audit_events 等后续业务表。

Revision ID: 0005_preview
Revises: 0004_review
Create Date: 2026-05-29

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_preview"
down_revision: str | None = "0004_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "preview_credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_asset_id", sa.Uuid(), nullable=False),
        sa.Column("target_version_id", sa.Uuid(), nullable=True),
        sa.Column("requester_user_id", sa.Uuid(), nullable=False),
        sa.Column("preview_type", sa.String(length=20), nullable=False),
        sa.Column("credential_status", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=256), nullable=False),
        sa.Column("credential_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("preview_entry_url", sa.String(length=500), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trace_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["target_asset_id"], ["knowledge_assets.id"]),
        sa.ForeignKeyConstraint(["target_version_id"], ["knowledge_asset_versions.id"]),
        sa.ForeignKeyConstraint(["requester_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_preview_status_expires",
        "preview_credentials",
        ["credential_status", "expires_at"],
    )
    op.create_index(
        "ix_preview_asset_requester",
        "preview_credentials",
        ["target_asset_id", "requester_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_preview_asset_requester", table_name="preview_credentials")
    op.drop_index("ix_preview_status_expires", table_name="preview_credentials")
    op.drop_table("preview_credentials")

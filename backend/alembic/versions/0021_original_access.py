"""original_access

PBC-06 原文访问申请与授权：建 original_access_requests + access_grants 两表。
部分唯一索引保证「同用户同资产至多一个 pending 申请」「同 grantee 同资产同类型至多一个
active 授权」（PG / SQLite 兼容）。只存安全枚举/UUID/时间/安全文本，绝不存原文 / secret。

Revision ID: 0021_original_access
Revises: 0020_personal_submissions
Create Date: 2026-06-02

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_original_access"
down_revision: str | None = "0020_personal_submissions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "original_access_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("requester_user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("requested_access_layer", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reviewer_user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["knowledge_assets.id"]),
        sa.ForeignKeyConstraint(["requester_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_oar_asset_status", "original_access_requests", ["asset_id", "status"])
    op.create_index("ix_oar_reviewer_status", "original_access_requests", ["reviewer_user_id", "status"])
    op.create_index(
        "uq_oar_one_pending", "original_access_requests",
        ["requester_user_id", "asset_id"], unique=True,
        sqlite_where=sa.text("status = 'pending'"),
        postgresql_where=sa.text("status = 'pending'"),
    )

    op.create_table(
        "access_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("grantee_user_id", sa.Uuid(), nullable=False),
        sa.Column("grant_type", sa.String(length=30), nullable=False),
        sa.Column("source_request_id", sa.Uuid(), nullable=True),
        sa.Column("granted_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["knowledge_assets.id"]),
        sa.ForeignKeyConstraint(["grantee_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["source_request_id"], ["original_access_requests.id"]),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["revoked_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_grant_grantee_asset_status", "access_grants",
        ["grantee_user_id", "asset_id", "status"],
    )
    op.create_index(
        "uq_grant_one_active", "access_grants",
        ["grantee_user_id", "asset_id", "grant_type"], unique=True,
        sqlite_where=sa.text("status = 'active'"),
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_grant_one_active", table_name="access_grants")
    op.drop_index("ix_grant_grantee_asset_status", table_name="access_grants")
    op.drop_table("access_grants")
    op.drop_index("uq_oar_one_pending", table_name="original_access_requests")
    op.drop_index("ix_oar_reviewer_status", table_name="original_access_requests")
    op.drop_index("ix_oar_asset_status", table_name="original_access_requests")
    op.drop_table("original_access_requests")

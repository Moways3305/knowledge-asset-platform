"""Add scheduled knowledge reviews, replacement lineage and correction verification."""

import sqlalchemy as sa

from alembic import op

revision = "0076_knowledge_review_loop"
down_revision = "0075_release_deployment"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("knowledge_assets") as batch:
        for name in ("review_due_at", "verified_at", "verified_updated_at"):
            batch.add_column(sa.Column(name, sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("verified_by_user_id", sa.Uuid()))
        batch.add_column(sa.Column("replacement_asset_id", sa.Uuid()))
        batch.create_foreign_key("fk_asset_verified_by", "users", ["verified_by_user_id"], ["id"])
        batch.create_foreign_key(
            "fk_asset_replacement", "knowledge_assets", ["replacement_asset_id"], ["id"]
        )
    op.create_table(
        "knowledge_corrections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("knowledge_assets.id"), nullable=False),
        sa.Column("reporter_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("resolution", sa.Text()),
        sa.Column("reported_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reported_fingerprint", sa.String(64), nullable=False),
        sa.Column("resolved_fingerprint", sa.String(64)),
        sa.Column("resolved_updated_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_asset_id", sa.Uuid(), sa.ForeignKey("knowledge_assets.id")),
        sa.Column("resolved_by_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_knowledge_corrections_asset_status", "knowledge_corrections", ["asset_id", "status"]
    )


def downgrade():
    op.drop_table("knowledge_corrections")
    with op.batch_alter_table("knowledge_assets") as batch:
        batch.drop_constraint("fk_asset_verified_by", type_="foreignkey")
        batch.drop_constraint("fk_asset_replacement", type_="foreignkey")
        for name in (
            "review_due_at",
            "verified_at",
            "verified_updated_at",
            "verified_by_user_id",
            "replacement_asset_id",
        ):
            batch.drop_column(name)

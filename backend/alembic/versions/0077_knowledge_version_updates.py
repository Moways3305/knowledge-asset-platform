"""Bind replacement uploads to their source document."""

import sqlalchemy as sa

from alembic import op

revision = "0077_knowledge_version_updates"
down_revision = "0076_knowledge_review_loop"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("ingest_tasks") as batch:
        batch.add_column(sa.Column("update_of_asset_id", sa.Uuid()))
        batch.add_column(sa.Column("update_of_version_id", sa.Uuid()))
        batch.add_column(sa.Column("update_version_label", sa.String(20)))
        batch.create_foreign_key(
            "fk_ingest_update_asset", "knowledge_assets", ["update_of_asset_id"], ["id"]
        )
        batch.create_foreign_key(
            "fk_ingest_update_version", "knowledge_asset_versions", ["update_of_version_id"], ["id"]
        )
        batch.create_index("ix_ingest_tasks_update_of_asset_id", ["update_of_asset_id"])


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT count(*) FROM ingest_tasks WHERE update_of_asset_id IS NOT NULL")
    ):
        raise RuntimeError(
            "Version update provenance exists; preserve this migration during rollback"
        )
    with op.batch_alter_table("ingest_tasks") as batch:
        batch.drop_index("ix_ingest_tasks_update_of_asset_id")
        batch.drop_constraint("fk_ingest_update_version", type_="foreignkey")
        batch.drop_constraint("fk_ingest_update_asset", type_="foreignkey")
        for name in ("update_version_label", "update_of_version_id", "update_of_asset_id"):
            batch.drop_column(name)

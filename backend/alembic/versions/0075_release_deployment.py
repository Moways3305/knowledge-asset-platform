"""Link release drafts to verified deployments; preserve legacy published notes."""

import sqlalchemy as sa

from alembic import op

revision = "0075_release_deployment"
down_revision = "0074_release_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("release_notes") as batch:
        batch.alter_column("created_by", existing_type=sa.Uuid(), nullable=True)
        batch.add_column(sa.Column("source_commit", sa.String(40)))
        batch.add_column(sa.Column("previous_commit", sa.String(40)))
        batch.add_column(sa.Column("manifest_digest", sa.String(64)))
        batch.add_column(sa.Column("deployed_at", sa.DateTime(timezone=True)))
        batch.create_unique_constraint("uq_release_notes_source_commit", ["source_commit"])


def downgrade() -> None:
    # An automated author must never be replaced with an invented human identity.
    count = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM release_notes WHERE created_by IS NULL")
    )
    if count:
        raise RuntimeError(
            "Automated release notes exist; retain migration 0075 when rolling back code"
        )
    with op.batch_alter_table("release_notes") as batch:
        batch.drop_constraint("uq_release_notes_source_commit", type_="unique")
        for column in ("source_commit", "previous_commit", "manifest_digest", "deployed_at"):
            batch.drop_column(column)
        batch.alter_column("created_by", existing_type=sa.Uuid(), nullable=False)

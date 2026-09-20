"""Administrator release notes and per-user read receipts."""

import sqlalchemy as sa

from alembic import op

revision = "0074_release_notes"
down_revision = "0073_parse_reconcile_lease"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "release_notes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("version", sa.String(40), nullable=False, unique=True),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("entries", sa.JSON(), nullable=False),
        sa.Column("notify_users", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("published_by", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_release_notes_published", "release_notes", ["published_at", "notify_users"])
    op.create_table(
        "release_note_reads",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column(
            "release_id",
            sa.Uuid(),
            sa.ForeignKey("release_notes.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("release_note_reads")
    op.drop_index("ix_release_notes_published", table_name="release_notes")
    op.drop_table("release_notes")

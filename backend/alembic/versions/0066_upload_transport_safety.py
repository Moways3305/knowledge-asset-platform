"""upload transport batches and durable manifest

Revision ID: 0066_upload_transport_safety
Revises: 0065_ocr_ingest_recovery
"""

import sqlalchemy as sa

from alembic import op

revision = "0066_upload_transport_safety"
down_revision = "0065_ocr_ingest_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "upload_sessions",
        sa.Column("upload_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "upload_sessions",
        sa.Column("next_transport_batch_index", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("upload_sessions", sa.Column("target_scope", sa.String(20), nullable=True))
    op.add_column("upload_sessions", sa.Column("target_project_id", sa.Uuid(), nullable=True))
    op.add_column(
        "upload_session_items", sa.Column("client_file_key", sa.String(100), nullable=True)
    )
    op.add_column(
        "upload_session_items", sa.Column("suggested_formed_on", sa.String(10), nullable=True)
    )
    op.add_column(
        "upload_session_items", sa.Column("transport_batch_index", sa.Integer(), nullable=True)
    )
    op.create_unique_constraint(
        "uq_upload_item_client_file_key",
        "upload_session_items",
        ["session_id", "client_file_key"],
    )
    op.create_table(
        "upload_transport_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.String(100), nullable=False),
        sa.Column("batch_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False),
        sa.Column("raw_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["upload_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "batch_id", name="uq_upload_transport_batch_id"),
        sa.UniqueConstraint("session_id", "batch_index", name="uq_upload_transport_batch_index"),
    )
    op.create_index(
        "ix_upload_transport_batches_session_id",
        "upload_transport_batches",
        ["session_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_upload_transport_batches_session_id", table_name="upload_transport_batches")
    op.drop_table("upload_transport_batches")
    op.drop_constraint("uq_upload_item_client_file_key", "upload_session_items", type_="unique")
    op.drop_column("upload_session_items", "transport_batch_index")
    op.drop_column("upload_session_items", "suggested_formed_on")
    op.drop_column("upload_session_items", "client_file_key")
    op.drop_column("upload_sessions", "next_transport_batch_index")
    op.drop_column("upload_sessions", "target_project_id")
    op.drop_column("upload_sessions", "target_scope")
    op.drop_column("upload_sessions", "upload_completed")

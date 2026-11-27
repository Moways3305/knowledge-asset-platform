"""Private AI workspace sessions, runs, documents and ordered event journal."""

import sqlalchemy as sa
from alembic import op

revision = "0096_ai_workspace"
down_revision = "0095_knowledge_tasks"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ai_workspace_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("active_run_id", sa.Uuid()),
        sa.Column("event_seq", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_workspace_owner", "ai_workspace_sessions", ["user_id", "role", "updated_at"]
    )
    op.create_table(
        "ai_workspace_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("ai_workspace_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("model_ref", sa.String(200), nullable=False),
        sa.Column("context_key", sa.String(80)),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("retry_of", sa.Uuid()),
        sa.Column("claim", sa.Uuid()),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("source_refs", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(50)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_workspace_run_recovery", "ai_workspace_runs", ["status", "lease_until"])
    op.create_index("ix_ai_workspace_runs_session_id", "ai_workspace_runs", ["session_id"])
    op.create_table(
        "ai_workspace_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("ai_workspace_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("ai_workspace_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ai_workspace_messages_session_id", "ai_workspace_messages", ["session_id"])
    op.create_table(
        "ai_workspace_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("ai_workspace_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(40), nullable=False),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "seq", name="uq_workspace_event_seq"),
    )
    op.create_table(
        "ai_workspace_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("ai_workspace_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("ai_workspace_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_ai_workspace_artifacts_session_id", "ai_workspace_artifacts", ["session_id"]
    )


def downgrade():
    for table in (
        "ai_workspace_artifacts",
        "ai_workspace_events",
        "ai_workspace_messages",
        "ai_workspace_runs",
        "ai_workspace_sessions",
    ):
        op.drop_table(table)

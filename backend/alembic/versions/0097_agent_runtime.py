"""Durable agent checkpoints, tool intents and approval receipts."""

import sqlalchemy as sa

from alembic import op

revision = "0097_agent_runtime"
down_revision = "0096_ai_workspace"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("ai_workspace_messages", "ai_workspace_artifacts"):
        op.add_column(
            table,
            sa.Column("source_refs", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        )
    # Freeze historical descendants' original provenance before runs can refresh
    # their working context; refreshing a run must never re-expose an old draft.
    runs = sa.table(
        "ai_workspace_runs", sa.column("id", sa.Uuid()), sa.column("source_refs", sa.JSON())
    )
    for name in ("ai_workspace_messages", "ai_workspace_artifacts"):
        records = sa.table(
            name, sa.column("run_id", sa.Uuid()), sa.column("source_refs", sa.JSON())
        )
        op.execute(
            records.update().values(
                source_refs=sa.select(runs.c.source_refs)
                .where(runs.c.id == records.c.run_id)
                .scalar_subquery()
            )
        )
    op.add_column("ai_workspace_sessions", sa.Column("agent_key", sa.String(80)))
    op.add_column(
        "ai_workspace_runs",
        sa.Column("runtime_state", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "ai_workspace_runs",
        sa.Column("step_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "ai_workspace_runs",
        sa.Column("max_steps", sa.Integer(), nullable=False, server_default="24"),
    )
    op.add_column("ai_workspace_runs", sa.Column("next_wake_at", sa.DateTime(timezone=True)))
    op.create_table(
        "ai_workspace_actions",
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
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("tool", sa.String(80), nullable=False),
        sa.Column("label", sa.String(160), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("observation", sa.JSON(), nullable=False),
        sa.Column("source_refs", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("waiting", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "seq", name="uq_workspace_action_seq"),
    )
    op.create_index("ix_ai_workspace_actions_session_id", "ai_workspace_actions", ["session_id"])


def downgrade():
    for table in ("ai_workspace_messages", "ai_workspace_artifacts"):
        op.drop_column(table, "source_refs")
    op.drop_table("ai_workspace_actions")
    for name in ("next_wake_at", "max_steps", "step_count", "runtime_state"):
        op.drop_column("ai_workspace_runs", name)
    op.drop_column("ai_workspace_sessions", "agent_key")

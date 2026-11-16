"""Add opt-in knowledge maintenance Agent without changing existing assets."""

import sqlalchemy as sa

from alembic import op

revision = "0089_maintenance_agent"
down_revision = "0088_outbox_consumption"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "maintenance_agent_digests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), nullable=False),
        sa.Column("day", sa.String(length=10), nullable=False),
        sa.Column("issue_ids", sa.JSON(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recipient_id", "day", name="uq_maintenance_digest_recipient_day"),
    )
    op.create_table(
        "maintenance_agent_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("library_key", sa.String(length=60), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("content_authorized", sa.Boolean(), nullable=False),
        sa.Column("authorized_by", sa.Uuid(), nullable=False),
        sa.Column("authorized_role", sa.String(length=30), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("last_scheduled_day", sa.String(length=10), nullable=True),
        sa.Column("schedule_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_full_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=60), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["authorized_by"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("library_key"),
    )
    op.create_table(
        "maintenance_agent_checks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("policy_revision", sa.Integer(), nullable=False),
        sa.Column("coverage", sa.JSON(), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["knowledge_assets.id"],
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["maintenance_agent_policies.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("policy_id", "asset_id", name="uq_maintenance_check_asset"),
    )
    op.create_table(
        "maintenance_agent_issues",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=True),
        sa.Column("rule", sa.String(length=60), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("related_key", sa.String(length=36), nullable=False),
        sa.Column("related_asset_id", sa.Uuid(), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("suspected", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("snooze_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["knowledge_assets.id"],
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["maintenance_agent_policies.id"],
        ),
        sa.ForeignKeyConstraint(
            ["related_asset_id"],
            ["knowledge_assets.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "policy_id", "asset_id", "rule", "related_key", name="uq_maintenance_issue_fact"
        ),
    )
    op.create_index(
        "ix_maintenance_issue_policy_status",
        "maintenance_agent_issues",
        ["policy_id", "status"],
        unique=False,
    )
    op.create_table(
        "maintenance_agent_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("policy_revision", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("includes_l5", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("target_asset_id", sa.Uuid(), nullable=True),
        sa.Column("cursor", sa.Uuid(), nullable=True),
        sa.Column("target_count", sa.Integer(), nullable=False),
        sa.Column("completed_count", sa.Integer(), nullable=False),
        sa.Column("incomplete_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("claim_token", sa.String(length=36), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_progress_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["maintenance_agent_policies.id"],
        ),
        sa.ForeignKeyConstraint(
            ["target_asset_id"],
            ["knowledge_assets.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_maintenance_runs_status_lease",
        "maintenance_agent_runs",
        ["status", "lease_until"],
        unique=False,
    )
    op.create_table(
        "maintenance_agent_issue_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("issue_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
        ),
        sa.ForeignKeyConstraint(
            ["issue_id"],
            ["maintenance_agent_issues.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_maintenance_events_issue",
        "maintenance_agent_issue_events",
        ["issue_id", "created_at"],
        unique=False,
    )


def downgrade():
    op.drop_table("maintenance_agent_issue_events")
    op.drop_table("maintenance_agent_runs")
    op.drop_table("maintenance_agent_issues")
    op.drop_table("maintenance_agent_checks")
    op.drop_table("maintenance_agent_policies")
    op.drop_table("maintenance_agent_digests")

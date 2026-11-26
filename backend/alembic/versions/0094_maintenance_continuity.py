"""Keep digest membership and replacement rechecks durable."""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "0094_maintenance_continuity"
down_revision = "0093_optional_knowledge_review"
branch_labels = None
depends_on = None

digests = sa.table(
    "maintenance_agent_digests", sa.column("id", sa.Uuid), sa.column("issue_ids", sa.JSON)
)
members = sa.table(
    "maintenance_digest_issues", sa.column("digest_id", sa.Uuid), sa.column("issue_id", sa.Uuid)
)


def upgrade():
    op.add_column(
        "maintenance_agent_issues",
        sa.Column("requires_recheck", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        members.name,
        sa.Column(
            "digest_id", sa.Uuid(), sa.ForeignKey("maintenance_agent_digests.id"), primary_key=True
        ),
        sa.Column(
            "issue_id", sa.Uuid(), sa.ForeignKey("maintenance_agent_issues.id"), primary_key=True
        ),
    )
    op.create_index("ix_maintenance_digest_issues_issue_id", members.name, ["issue_id"])
    op.create_index(
        "ix_maintenance_issue_recheck_status",
        "maintenance_agent_issues",
        ["requires_recheck", "status", "asset_id"],
    )
    op.create_table(
        "maintenance_issue_aliases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "issue_id",
            sa.Uuid(),
            sa.ForeignKey("maintenance_agent_issues.id"),
            nullable=False,
            index=True,
        ),
    )
    db = op.get_bind()
    for digest_id, ids in db.execute(sa.select(digests.c.id, digests.c.issue_ids)):
        if ids:
            db.execute(
                members.insert(),
                [{"digest_id": digest_id, "issue_id": uuid.UUID(i)} for i in set(ids)],
            )
    op.drop_column(digests.name, "issue_ids")
    # Only recover issues retired by confirmed replacement, after the archive timestamp.
    op.execute("""
        UPDATE maintenance_agent_issues SET requires_recheck = true
        WHERE status = 'not_applicable' AND rule != 'missing_review_date'
        AND EXISTS (
            SELECT 1 FROM knowledge_assets a WHERE a.id = maintenance_agent_issues.asset_id
            AND a.asset_status = 'archived' AND a.deleted_at IS NULL
            AND a.replacement_asset_id IS NOT NULL
            AND maintenance_agent_issues.updated_at >= a.archived_at
            AND (SELECT e.action FROM maintenance_agent_issue_events e
                 WHERE e.issue_id = maintenance_agent_issues.id
                 ORDER BY e.created_at DESC, e.id DESC LIMIT 1) = 'fact_reconciled'
        )
    """)


def downgrade():
    op.add_column(
        digests.name, sa.Column("issue_ids", sa.JSON(), nullable=False, server_default="[]")
    )
    db = op.get_bind()
    for digest_id in db.scalars(sa.select(digests.c.id)):
        ids = db.scalars(sa.select(members.c.issue_id).where(members.c.digest_id == digest_id))
        db.execute(
            digests.update()
            .where(digests.c.id == digest_id)
            .values(issue_ids=[str(i) for i in ids])
        )
    op.drop_table("maintenance_issue_aliases")
    op.drop_table(members.name)
    op.drop_index("ix_maintenance_issue_recheck_status", table_name="maintenance_agent_issues")
    op.drop_column("maintenance_agent_issues", "requires_recheck")

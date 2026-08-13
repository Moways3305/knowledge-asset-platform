"""directory migration candidates

Revision ID: 0062_directory_migration_candidates
Revises: 0061_governed_directories
"""

from alembic import op
import sqlalchemy as sa

revision = "0062_directory_migration_candidates"
down_revision = "0061_governed_directories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "validation_evidences", sa.Column("idempotency_key", sa.String(100), nullable=True)
    )
    op.create_index(
        "uq_validation_evidence_idempotency",
        "validation_evidences",
        ["submitted_by", "related_asset_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_table(
        "directory_migration_candidates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("old_category", sa.String(255), nullable=True),
        sa.Column("suggested_directory_key", sa.String(100), nullable=True),
        sa.Column("legacy_reference_key", sa.String(100), nullable=True),
        sa.Column("candidate_source", sa.String(40), nullable=False),
        sa.Column("confidence", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("rule_version", sa.Integer(), nullable=True),
        sa.Column("failure_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["knowledge_assets.id"]),
        sa.ForeignKeyConstraint(["version_id"], ["knowledge_asset_versions.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version_id", name="uq_directory_migration_candidate_version"),
    )
    op.create_index(
        "ix_directory_migration_status_scope",
        "directory_migration_candidates",
        ["status", "scope"],
    )
    op.create_index(
        "ix_directory_migration_project_status",
        "directory_migration_candidates",
        ["project_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_directory_migration_project_status", table_name="directory_migration_candidates"
    )
    op.drop_index(
        "ix_directory_migration_status_scope", table_name="directory_migration_candidates"
    )
    op.drop_table("directory_migration_candidates")
    op.drop_index("uq_validation_evidence_idempotency", table_name="validation_evidences")
    op.drop_column("validation_evidences", "idempotency_key")

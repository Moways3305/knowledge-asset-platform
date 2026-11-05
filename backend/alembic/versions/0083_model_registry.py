"""Add versioned provider connections and model onboarding without migrating existing secrets."""

import sqlalchemy as sa

from alembic import op

revision = "0083_model_registry"
down_revision = "0082_withdrawn_review_status"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "provider_connections",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("config_ciphertext", sa.Text(), nullable=False),
        sa.Column("key_ciphertext", sa.Text(), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("credential_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "registered_models",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column(
            "connection_id", sa.Uuid(), sa.ForeignKey("provider_connections.id"), nullable=False
        ),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("model_name", sa.String(200), nullable=False),
        sa.Column("capability", sa.String(20), nullable=False),
        sa.Column("dimension", sa.Integer()),
        sa.Column("usages", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("tested_signature", sa.String(100)),
        sa.Column("test_status", sa.String(30), nullable=False),
        sa.Column("test_code", sa.String(60)),
        sa.Column("tested_at", sa.DateTime(timezone=True)),
        sa.Column("test_duration_ms", sa.Integer()),
        sa.Column("observed_dimension", sa.Integer()),
        sa.Column("bindings", sa.JSON(), nullable=False),
        sa.Column("external_id", sa.Uuid(), sa.ForeignKey("content_generation_models.id")),
        sa.Column("weknora_id", sa.String(200)),
        sa.Column("creation_uncertain", sa.String(100)),
        sa.Column("operation_token", sa.String(40)),
        sa.Column("operation_started", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.add_column(
        "content_generation_models",
        sa.Column("config_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("content_generation_models", sa.Column("tested_version", sa.Integer()))


def downgrade():
    op.drop_column("content_generation_models", "tested_version")
    op.drop_column("content_generation_models", "config_version")
    op.drop_table("registered_models")
    op.drop_table("provider_connections")

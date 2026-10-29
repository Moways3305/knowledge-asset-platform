"""Index literal body identifiers without optional PostgreSQL extensions."""

import sqlalchemy as sa

from alembic import op

revision = "0081_chunk_identifier_search"
down_revision = "0080_preview_requester_role"
branch_labels = None
depends_on = None


def upgrade():
    # A transactional build indexes existing rows and is automatically maintained
    # on future inserts/updates. It permits reads but blocks writes to chunks
    # during the build; schedule deployment accordingly for large installations.
    op.create_index(
        "ix_knowledge_chunks_identifier_vector",
        "knowledge_asset_chunks",
        [
            sa.text(
                "to_tsvector('simple'::regconfig, "
                "regexp_replace(content_text, '[^A-Za-z0-9]+', ' ', 'g'))"
            )
        ],
        postgresql_using="gin",
    )


def downgrade():
    op.drop_index("ix_knowledge_chunks_identifier_vector", table_name="knowledge_asset_chunks")

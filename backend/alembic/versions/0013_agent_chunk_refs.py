"""agent_chunk_refs

R3 两阶段检索：给 agent_gateway_decision_items / agent_call_citations 加 chunk 级引用列。
- target_weknora_chunk_ref / cited_weknora_chunk_ref：WeKnora chunk 引用，**server-only**，
  视同 storage_ref，绝不外泄。
- cited_snippet / cited_seq：脱敏后引用片段 + 安全序号（可对外）。
不动其它表、不新建表。

Revision ID: 0013_agent_chunk_refs
Revises: 0012_llm_draft
Create Date: 2026-06-01

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_agent_chunk_refs"
down_revision: str | None = "0012_llm_draft"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_gateway_decision_items",
        sa.Column("target_weknora_chunk_ref", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "agent_call_citations",
        sa.Column("cited_weknora_chunk_ref", sa.String(length=256), nullable=True),
    )
    op.add_column(
        "agent_call_citations",
        sa.Column("cited_snippet", sa.Text(), nullable=True),
    )
    op.add_column(
        "agent_call_citations",
        sa.Column("cited_seq", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_call_citations", "cited_seq")
    op.drop_column("agent_call_citations", "cited_snippet")
    op.drop_column("agent_call_citations", "cited_weknora_chunk_ref")
    op.drop_column("agent_gateway_decision_items", "target_weknora_chunk_ref")

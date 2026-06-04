"""create_agent_gateway_tables

建立 Agent / Dify Gateway 四张表（IMPLEMENT-08 最小闭环）：
agent_calls / agent_gateway_decisions / agent_gateway_decision_items /
agent_call_citations。

不创建 agent_whitelist_rules / agent_registry / permission_rules / access_grants /
original_access_requests / audit_events / 向量索引 / Dify 配置密钥等表。

Revision ID: 0006_agent
Revises: 0005_preview
Create Date: 2026-05-29

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_agent"
down_revision: str | None = "0005_preview"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_calls",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("caller_user_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("model_key", sa.String(length=50), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("capability", sa.String(length=30), nullable=False),
        sa.Column("call_status", sa.String(length=20), nullable=False),
        sa.Column("denied_reason", sa.String(length=50), nullable=True),
        sa.Column("trace_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["caller_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_calls_caller_created", "agent_calls", ["caller_user_id", "created_at"]
    )
    op.create_index("ix_agent_calls_project", "agent_calls", ["project_id"])

    op.create_table(
        "agent_gateway_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("caller_user_id", sa.Uuid(), nullable=False),
        sa.Column("decision_status", sa.String(length=20), nullable=False),
        sa.Column("discovery_allowed", sa.Boolean(), nullable=False),
        sa.Column("summary_allowed", sa.Boolean(), nullable=False),
        sa.Column("original_allowed", sa.Boolean(), nullable=False),
        sa.Column("allowed_scope", sa.String(length=50), nullable=True),
        sa.Column("denied_reason", sa.String(length=50), nullable=True),
        sa.Column("effective_access_source", sa.String(length=30), nullable=True),
        sa.Column("trace_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["call_id"], ["agent_calls.id"]),
        sa.ForeignKeyConstraint(["caller_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_decisions_call", "agent_gateway_decisions", ["call_id"]
    )

    op.create_table(
        "agent_gateway_decision_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("caller_user_id", sa.Uuid(), nullable=False),
        sa.Column("target_asset_id", sa.Uuid(), nullable=False),
        sa.Column("target_chunk_id", sa.Uuid(), nullable=True),
        sa.Column("target_project_id", sa.Uuid(), nullable=True),
        sa.Column("target_scope", sa.String(length=20), nullable=False),
        sa.Column("target_confidentiality_level", sa.String(length=2), nullable=False),
        sa.Column("target_ai_access_level", sa.String(length=2), nullable=False),
        sa.Column("discovery_allowed", sa.Boolean(), nullable=False),
        sa.Column("summary_allowed", sa.Boolean(), nullable=False),
        sa.Column("original_allowed", sa.Boolean(), nullable=False),
        sa.Column("returned_layer", sa.String(length=20), nullable=True),
        sa.Column("effective_access_source", sa.String(length=30), nullable=True),
        sa.Column("denied_reason", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["decision_id"], ["agent_gateway_decisions.id"]),
        sa.ForeignKeyConstraint(["call_id"], ["agent_calls.id"]),
        sa.ForeignKeyConstraint(["caller_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["target_asset_id"], ["knowledge_assets.id"]),
        sa.ForeignKeyConstraint(["target_chunk_id"], ["knowledge_asset_chunks.id"]),
        sa.ForeignKeyConstraint(["target_project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_items_decision", "agent_gateway_decision_items", ["decision_id"]
    )
    op.create_index("ix_agent_items_call", "agent_gateway_decision_items", ["call_id"])

    op.create_table(
        "agent_call_citations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Uuid(), nullable=False),
        sa.Column("decision_item_id", sa.Uuid(), nullable=False),
        sa.Column("cited_asset_id", sa.Uuid(), nullable=False),
        sa.Column("cited_chunk_id", sa.Uuid(), nullable=True),
        sa.Column("used_access_layer", sa.String(length=20), nullable=False),
        sa.Column("cited_zone", sa.String(length=20), nullable=False),
        sa.Column("citation_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["call_id"], ["agent_calls.id"]),
        sa.ForeignKeyConstraint(
            ["decision_item_id"], ["agent_gateway_decision_items.id"]
        ),
        sa.ForeignKeyConstraint(["cited_asset_id"], ["knowledge_assets.id"]),
        sa.ForeignKeyConstraint(["cited_chunk_id"], ["knowledge_asset_chunks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_citations_call", "agent_call_citations", ["call_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_citations_call", table_name="agent_call_citations")
    op.drop_table("agent_call_citations")
    op.drop_index("ix_agent_items_call", table_name="agent_gateway_decision_items")
    op.drop_index("ix_agent_items_decision", table_name="agent_gateway_decision_items")
    op.drop_table("agent_gateway_decision_items")
    op.drop_index("ix_agent_decisions_call", table_name="agent_gateway_decisions")
    op.drop_table("agent_gateway_decisions")
    op.drop_index("ix_agent_calls_project", table_name="agent_calls")
    op.drop_index("ix_agent_calls_caller_created", table_name="agent_calls")
    op.drop_table("agent_calls")

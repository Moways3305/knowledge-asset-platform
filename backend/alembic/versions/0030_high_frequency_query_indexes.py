"""high_frequency_query_indexes

为高频查询列补索引（PostgreSQL 不自动给外键建索引；列表页 / 入库面板 / 索引状态聚合
的过滤列原本无显式索引）。**仅新增索引，不改表结构 / 不改业务语义**。

索引（7 个）：
- knowledge_assets: owner_user_id、project_id、(scope, asset_status) 复合、created_at
- ingest_tasks: created_by、target_project_id
  （status 不再单列建索引：0003 已有 (status, created_at) 复合索引，其最左前缀即 status，
   `WHERE status = ...` 直接命中，单列重复索引只增写入/迁移成本、收益甚微。）
- knowledge_asset_versions: index_status

方言分支：
- PostgreSQL（生产 / CI migration job）：`CREATE/DROP INDEX CONCURRENTLY` 避免长锁。
  CONCURRENTLY 不能在事务内执行，故经 `op.get_context().autocommit_block()`（Alembic 标准
  方式）在事务外执行——**不**用手动 `op.execute("COMMIT")`。`IF NOT EXISTS/IF EXISTS`
  使其可重入。
- SQLite（create_all 测试库 / 本地快速验证）：不支持 CONCURRENTLY，退回
  `op.create_index` / `op.drop_index`。

可逆：downgrade 按相反顺序 drop 全部新增索引。

Revision ID: 0030_high_frequency_query_indexes
Revises: 0029_weknora_kb_display_name
Create Date: 2026-06-17

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0030_high_frequency_query_indexes"
down_revision: str | None = "0029_weknora_kb_display_name"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (索引名, 表名, 列)。复合索引列顺序＝查询过滤顺序（scope 先、asset_status 后，匹配
# 列表页"按 scope 选库 + 按 zone/状态过滤"的访问模式）。
_INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("ix_knowledge_assets_owner_user_id", "knowledge_assets", ("owner_user_id",)),
    ("ix_knowledge_assets_project_id", "knowledge_assets", ("project_id",)),
    ("ix_knowledge_assets_scope_status", "knowledge_assets", ("scope", "asset_status")),
    ("ix_knowledge_assets_created_at", "knowledge_assets", ("created_at",)),
    ("ix_ingest_tasks_created_by", "ingest_tasks", ("created_by",)),
    ("ix_ingest_tasks_target_project_id", "ingest_tasks", ("target_project_id",)),
    ("ix_kav_index_status", "knowledge_asset_versions", ("index_status",)),
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # CONCURRENTLY 必须在事务外执行 → autocommit_block（非手动 COMMIT）。
        with op.get_context().autocommit_block():
            for name, table, cols in _INDEXES:
                op.execute(
                    f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table} ({', '.join(cols)})"
                )
    else:
        for name, table, cols in _INDEXES:
            op.create_index(name, table, list(cols))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            for name, _table, _cols in reversed(_INDEXES):
                op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
    else:
        for name, table, _cols in reversed(_INDEXES):
            op.drop_index(name, table_name=table)

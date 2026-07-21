"""agent_whitelist_unique_provider_user

为 agent_whitelist_rules 增加 (provider, bound_user_id) 部分唯一索引（WHERE
bound_user_id IS NOT NULL），防止自助 WorkBuddy 接入为同一用户重复生成多行注册，
从根上消除 _find_rule 命中多行 → MultipleResultsFound → 自助端点 500 的隐患。

前置清理：历史上可能已存在 (provider, bound_user_id) 重复行（旧逻辑无此约束）。
直接建唯一索引会失败，故迁移中先按 (provider, bound_user_id) 分组，保留每组最新一行
（created_at desc 取首行），将其余行的 enabled 置为 false（不物理删除，安全可回溯）。
清理后再创建部分唯一索引。

幂等：
- 清理 UPDATE 只影响"非保留行"，重复运行无副作用（保留行集合不变）。
- 索引创建走 `IF NOT EXISTS`（PG）/ Alembic create_index（SQLite 重复建会被忽略）。

方言分支：
- PostgreSQL（生产 / CI migration job）：`CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS`
  避免长锁；CONCURRENTLY 不能在事务内执行，故经 `op.get_context().autocommit_block()`。
- SQLite（create_all 测试库 / 本地快速验证）：不支持 CONCURRENTLY，退回
  `op.create_index(..., unique=True, sqlite_where=...)`。

Revision ID: 0044_agent_whitelist_unique_provider_user
Revises: 0043_indexing_ops_health
Create Date: 2026-07-21

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0044_agent_whitelist_unique_provider_user"
down_revision: str | None = "0043_indexing_ops_health"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# 部分唯一索引名（命名风格沿用 0043 的 uq_<table>_<purpose>）。
_INDEX_NAME = "uq_agent_whitelist_provider_bound_user"
_TABLE = "agent_whitelist_rules"


def upgrade() -> None:
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # 1) 清理历史重复行：每组 (provider, bound_user_id) 保留最新一行
    #    （created_at desc 取首行），其余行 enabled 置 false。
    #    只影响 bound_user_id IS NOT NULL 的行（legacy dify 行 bound_user_id
    #    为 NULL，本就允许同 provider 多行，不受此约束）。
    #    使用子查询锁定"非保留行 id 集合"，单条 UPDATE 原子完成，可重入。
    # ------------------------------------------------------------------
    if bind.dialect.name == "postgresql":
        # PostgreSQL：用 DISTINCT ON 取每组首行（created_at desc），其余禁用。
        op.execute(
            sa.text(
                """
                UPDATE agent_whitelist_rules AS r
                SET enabled = false
                WHERE r.bound_user_id IS NOT NULL
                  AND r.id NOT IN (
                      SELECT DISTINCT ON (provider, bound_user_id) id
                      FROM agent_whitelist_rules
                      WHERE bound_user_id IS NOT NULL
                      ORDER BY provider, bound_user_id, created_at DESC, id DESC
                  )
                  AND r.enabled = true
                """
            )
        )
    else:
        # SQLite / 其它：用 ROW_NUMBER() 窗口函数取每组首行（兼容 SQLite 3.25+）。
        op.execute(
            sa.text(
                """
                UPDATE agent_whitelist_rules
                SET enabled = false
                WHERE id IN (
                    SELECT id FROM (
                        SELECT id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY provider, bound_user_id
                                   ORDER BY created_at DESC, id DESC
                               ) AS rn
                        FROM agent_whitelist_rules
                        WHERE bound_user_id IS NOT NULL
                    )
                    WHERE rn > 1
                )
                  AND enabled = true
                """
            )
        )

    # ------------------------------------------------------------------
    # 2) 创建部分唯一索引：仅约束 bound_user_id IS NOT NULL 的行。
    #    legacy dify 行（bound_user_id NULL）不受约束，仍可同 provider 多行。
    # ------------------------------------------------------------------
    partial_where = sa.text("bound_user_id IS NOT NULL")
    if bind.dialect.name == "postgresql":
        # CONCURRENTLY 必须在事务外执行 → autocommit_block（非手动 COMMIT）。
        with op.get_context().autocommit_block():
            op.execute(
                f"CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX_NAME} "
                f"ON {_TABLE} (provider, bound_user_id) WHERE bound_user_id IS NOT NULL"
            )
    else:
        # SQLite：不支持 CONCURRENTLY；create_index 自身可重入（已存在时 Alembic 跳过）。
        op.create_index(
            _INDEX_NAME,
            _TABLE,
            ["provider", "bound_user_id"],
            unique=True,
            sqlite_where=partial_where,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME}")
    else:
        op.drop_index(_INDEX_NAME, table_name=_TABLE)

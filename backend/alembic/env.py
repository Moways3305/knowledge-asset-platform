"""Alembic environment.

Reads DATABASE_URL from the application settings / environment. The metadata
target is the shared declarative Base. No business models are imported yet
(IMPLEMENT-00); later tasks will import their models so autogenerate can see
them.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.db.base import Base

# 导入模型以填充 Base.metadata（供未来 autogenerate 使用）。
import app.models  # noqa: E402,F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the runtime DATABASE_URL (async driver) into the Alembic config.
config.set_main_option("sqlalchemy.url", get_settings().database_url)

# Target metadata for autogenerate. Empty until models are added later.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _ensure_version_table_width(connection: Connection) -> None:
    """先把 alembic_version.version_num 建宽 / 改宽到 VARCHAR(64)（幂等）。

    alembic 默认版本表列为 VARCHAR(32)，而本仓库存在长度 >32 的 revision id
    （0026_ingest_desensitization_metadata，36 字符）：PostgreSQL 下 upgrade 经过
    该版本时写版本表会因截断失败，且任何已有库都无法越过 0025。此处只动 alembic
    的簿记表，不改任何迁移内容；已是 64 宽时 ALTER 为空操作。
    """
    if connection.dialect.name != "postgresql":
        return
    connection.execute(text(
        "CREATE TABLE IF NOT EXISTS alembic_version ("
        "version_num VARCHAR(64) NOT NULL, "
        "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
    ))
    connection.execute(text(
        "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)"
    ))
    # 立即提交：SQLAlchemy 2.0 下上面的 execute 会在连接上自动开启事务；若不提交，
    # alembic 随后的迁移事务会嵌在这个外层事务里、连接关闭时整体回滚（迁移白跑）。
    connection.commit()


def do_run_migrations(connection: Connection) -> None:
    _ensure_version_table_width(connection)
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())

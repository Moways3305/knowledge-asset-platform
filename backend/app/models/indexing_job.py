"""索引运维任务 ORM 模型。

一张轻量运维任务表 `indexing_operation_jobs`：记录运维发起的**批量 retry-index** /
**显式 reparse** 后台作业的安全状态与统计，供 ops 面板查询。

安全：本表**绝不**保存原文 / 文件名 / storage ref / source ref / WeKnora kb·doc id /
上游原始错误 message。`scope_filter` 只存安全筛选条件（scope / project_id / 状态 / limit）；
`error_code` 必须经 `error_catalog.safe_code()` 归一；`error_message` 用安全用户/运营文案。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.utils import utc_now


class IndexingOperationJob(Base):
    """索引运维后台作业（批量 retry-index / 显式 reparse）。"""

    __tablename__ = "indexing_operation_jobs"
    __table_args__ = (
        Index(
            "uq_indexing_active_target_retry",
            "target_asset_id",
            unique=True,
            sqlite_where=text(
                "target_asset_id IS NOT NULL AND operation_type = 'retry_index' "
                "AND status IN ('queued', 'running')"
            ),
            postgresql_where=text(
                "target_asset_id IS NOT NULL AND operation_type = 'retry_index' "
                "AND status IN ('queued', 'running')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # retry_index | reparse
    operation_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # queued | running | completed | completed_with_errors | failed
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    # 安全筛选条件（scope / project_id / statuses / limit）；绝不含原文 / 内部 ref。
    scope_filter: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    # 单条重试目标，仅供后端选择与数据库并发去重；绝不进入 API / 审计 / 日志。
    target_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("knowledge_assets.id"), nullable=True
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 安全目录 code（error_catalog.safe_code）+ 安全文案；绝不含上游原始 message / 内部 id。
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class IndexingOpsSnapshot(Base):
    """按小时聚合的安全索引运维快照。"""

    __tablename__ = "indexing_ops_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    bucket_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, unique=True
    )
    index_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    indexing: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    not_indexed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parse_pending: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parse_processing: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kb_init_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_jobs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_jobs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    queued_jobs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    oldest_queued_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class OpsRuntimeHeartbeat(Base):
    """worker / beat 的最近真实运行心跳，不保存节点标识。"""

    __tablename__ = "ops_runtime_heartbeats"

    component: Mapped[str] = mapped_column(String(20), primary_key=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

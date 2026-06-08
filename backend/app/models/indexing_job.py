"""索引运维任务 ORM 模型。

一张轻量运维任务表 `indexing_operation_jobs`：记录运维发起的**批量 retry-index** /
**显式 reparse** 后台作业的安全状态与统计，供 ops 面板查询。

安全：本表**绝不**保存原文 / 文件名 / storage ref / source ref / WeKnora kb·doc id /
上游原始错误 message。`scope_filter` 只存安全筛选条件（scope / project_id / 状态 / limit）；
`error_code` 必须经 `error_catalog.safe_code()` 归一；`error_message` 用安全用户/运营文案。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class IndexingOperationJob(Base):
    """索引运维后台作业（批量 retry-index / 显式 reparse）。"""

    __tablename__ = "indexing_operation_jobs"

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
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


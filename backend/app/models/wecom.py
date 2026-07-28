"""企业微信微盘扫描 ORM 模型（Path A）。

两张表（wecom_scan_configs / wecom_scan_records）：
- wecom_scan_configs：扫描目录配置（目录、scope、关联项目、启用、归属人）。
- wecom_scan_records：每次扫描的运行记录（计数 + 状态，仅安全运营元数据）。

安全红线：
- **绝不**存企微临时下载 URL / access_token / 授权码 / secret / 微盘 file_id 等敏感载体。
- 去重用内容 hash（落到 ingest_tasks.source_file_hash），本表不持有 file_id。
- error_message 仅安全文案，不含上游原始 payload / URL / token。

字段命名：采用 discovered/new/duplicate/failed_count + scan_status + error_type/message；
命名差异见 README。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.utils import utc_now


class WecomScanConfig(Base):
    __tablename__ = "wecom_scan_configs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # 人类可读配置名。
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    directory_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    # company / project（不引入新 scope 语义）。
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    related_project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id"), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 扫描发现的文件归属/创建人（IngestTask.created_by 用它，后续由该业务用户确认）。
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    scan_frequency: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class WecomProjectScanSpace(Base):
    """一项目一共享扫描空间映射；真实微盘引用只存在服务端。"""

    __tablename__ = "wecom_project_scan_spaces"
    __table_args__ = (UniqueConstraint("project_id", name="uq_wecom_project_scan_space_project"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False)
    # 企业微信真实空间标识，server-only；创建失败/进行中时为空。
    space_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # creating / ready / unavailable
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="creating")
    # ready / identity_link_required
    manager_access_status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="identity_link_required"
    )
    manager_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class WecomScanRecord(Base):
    __tablename__ = "wecom_scan_records"
    __table_args__ = (
        Index("ix_wecom_scan_records_config", "config_id", "created_at"),
        # 幂等：同 config + 非空 idempotency_key 唯一（部分唯一索引，PostgreSQL / SQLite>=3.8 均支持）。
        # 并发同 key 触发只会建一条记录；第二个插入命中唯一冲突，由服务层回滚后重查返回。
        Index(
            "uq_wecom_scan_idempotency",
            "config_id",
            "idempotency_key",
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL"),
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    config_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("wecom_scan_configs.id"), nullable=False
    )
    trace_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 幂等键（手动触发可携带 Idempotency-Key；同 config + key 命中已存在记录则不重扫）。
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    scan_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    scan_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    discovered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    new_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # running / completed / failed
    scan_status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    error_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

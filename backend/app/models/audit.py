"""审计日志 ORM 模型。

仅一张表 `audit_events`，字段严格对齐 BE-02 §4.7 / BE-09 §3。
（`asset_lifecycle_events` / `alert_rules` / `notification_records` 由各自模块定义。）

不可变原则（BE-09 §3.1）：写入即定稿，不提供 update/delete 原始事实的能力；
唯一允许的后续变化是异常处理三字段（is_processed / processed_by / processed_at）
或追加一条 `audit.exception_processed` 处理事件。

写入时脱敏（BE-09 §7.1）：snapshot / extra 根本不写入业务原文、客户数据、未脱敏
AI 正文、storage_ref、对象存储 URL/bucket、完整 preview token、Dify
api_key/workflow_id/dataset_id/kb_id/collection、向量库内部 ID 等。集中写入服务
`app.services.audit` 负责保证只放安全元数据。

枚举值（log_type / severity / action / 角色快照）以 String 存储 + 应用层 enum
校验，不使用 DB 原生 enum。snapshot / extra 用跨库 JSON 列。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_trace", "trace_id"),
        Index("ix_audit_events_logtype_created", "log_type", "created_at"),
        Index("ix_audit_events_action_created", "action", "created_at"),
        Index("ix_audit_events_actor", "actor_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    log_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    # 执行时角色快照（不随后续角色变更覆盖）。
    actor_company_role: Mapped[str | None] = mapped_column(String(30), nullable=True)
    actor_project_role: Mapped[str | None] = mapped_column(String(30), nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    before_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    severity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    processed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    device_info: Mapped[str | None] = mapped_column(String(500), nullable=True)
    login_result: Mapped[str | None] = mapped_column(String(20), nullable=True)
    trace_id: Mapped[str] = mapped_column(String(100), nullable=False)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


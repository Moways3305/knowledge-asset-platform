"""生命周期 / 告警 / 通知 ORM 模型。

落地三张治理表（对齐 BE-02 §4.7 / BE-10）：
- asset_lifecycle_events：资产生命周期事件事实（预警/候选/归档/重新启用）。
- alert_rules：告警/归档阈值规则（默认建议值落库、可配置，不写死硬编码）。
- notification_records：本地通知记录（不实现真实发送，仅安全元数据）。

字段说明：
- 归档不删除：生命周期事件是追加事实，不覆盖、不物理删除既有审计/业务数据。
- trace_id（asset_lifecycle_events）：为满足 API 契约 §14A 生命周期事件查询响应
  必含 `trace_id` 字段、并支持「预警→确认→状态变更」同链路串联而新增（BE-02 §4.7
  原表未列该列，属为贯穿 trace_id 的实现期补充，留待 reviewer 回写数据模型确认）。
- notification_records 只存安全元数据（标题 / 安全摘要内容），绝不存业务原文、
  storage_ref、对象存储 URL、完整 preview token、Dify api_key/workflow_id/dataset_id、
  向量库内部 ID 等（沿用 BE-09 §7 脱敏约束）。

枚举值以 String 存储 + 应用层校验，不使用 DB 原生 enum；通知渠道用跨库 JSON 列。
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
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AssetLifecycleEvent(Base):
    """资产生命周期事件（追加事实，不可改写）。"""

    __tablename__ = "asset_lifecycle_events"
    __table_args__ = (
        Index("ix_asset_lifecycle_events_asset", "asset_id", "created_at"),
        Index("ix_asset_lifecycle_events_trace", "trace_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_assets.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    old_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # system / user。人工动作记为 user；系统预警/扫描记为 system。
    triggered_by: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 关联审核任务（lifecycle_change）；仅作为可空元数据携带，不扩展 BE-06。
    review_task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    # 同链路串联用（预警→确认→状态变更→后续 Agent/preview 拒绝）。
    trace_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AlertRule(Base):
    """告警/归档阈值规则。阈值（如 730 天未调用 / 30 天预警期）作为可配置默认值落库。"""

    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    rule_name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    threshold: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    threshold_unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notification_channels: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    dedup_strategy: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class NotificationRecord(Base):
    """本地通知记录（不实现真实发送；只存安全元数据）。"""

    __tablename__ = "notification_records"
    __table_args__ = (
        Index("ix_notification_records_recipient", "recipient_user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    alert_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("alert_rules.id"), nullable=True
    )
    audit_event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("audit_events.id"), nullable=True
    )
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    send_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # R7：真实下发的投递元数据（安全）。send_attempts 计重试；failure_reason 仅安全 code/文案。
    send_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


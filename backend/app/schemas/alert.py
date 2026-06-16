"""Admin 告警设置 API 的请求 / 响应 schema。

alert_rules 承载归档阈值等可配置规则；notification_records 为本地通知记录，
只回安全元数据（标题 / 安全摘要内容），不回业务原文与内部敏感标识。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class AlertRuleOut(BaseModel):
    id: uuid.UUID
    rule_name: str
    severity: str
    threshold: float | None
    threshold_unit: str | None
    enabled: bool
    notification_channels: list[str]
    dedup_strategy: str | None
    updated_at: datetime


class AlertRulesResponse(BaseModel):
    items: list[AlertRuleOut]


class AlertRuleUpdateBody(BaseModel):
    enabled: bool | None = None
    threshold: float | None = None
    notification_channels: list[str] | None = None


class NotificationOut(BaseModel):
    id: uuid.UUID
    alert_rule_id: uuid.UUID | None
    audit_event_id: uuid.UUID | None
    recipient_user_id: uuid.UUID
    recipient_name: str | None
    channel: str
    title: str
    content: str
    send_status: str
    sent_at: datetime | None
    created_at: datetime


class NotificationsResponse(BaseModel):
    items: list[NotificationOut]

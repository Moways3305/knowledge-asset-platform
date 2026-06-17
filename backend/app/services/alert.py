"""告警规则 / 本地通知服务。

职责：
- alert_rules：归档阈值等规则的本地配置与查询；阈值默认建议值（730 天未调用 +
  30 天预警期）作为可配置规则落库，不写死在生命周期业务逻辑里。
- notification_records：本地通知记录的写入与查询。**不实现真实发送**（无邮件 /
  企微 / webhook / 外部 API），新建记录恒为 pending，内容仅安全元数据。

权限：三个 Admin Alert API 均要求 admin。审计：规则更新写
config.alert_rule_updated（经集中审计服务）。
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import User
from app.models.lifecycle import AlertRule, NotificationRecord
from app.schemas.alert import (
    AlertRuleOut,
    AlertRulesResponse,
    AlertRuleUpdateBody,
    NotificationOut,
    NotificationsResponse,
)
from app.schemas.enums import (
    AlertSeverity,
    AuditAction,
    AuditLogType,
    CompanyRole,
    NotificationChannel,
    NotificationStatus,
)
from app.schemas.permission import CallerContext
from app.services import audit as audit_service

# 默认归档阈值规则（与 lifecycle_change 审核口径一致）。
# 单条规则单阈值，故拆为两条：未调用天数阈值 + 预警期天数。
DEFAULT_ARCHIVE_RULES = [
    {
        "rule_name": "长期未调用归档预警",
        "severity": AlertSeverity.warning.value,
        "threshold": 730,
        "threshold_unit": "days",
        "dedup_strategy": "asset_id+event_type+time_window",
    },
    {
        "rule_name": "归档预警期",
        "severity": AlertSeverity.warning.value,
        "threshold": 30,
        "threshold_unit": "days",
        "dedup_strategy": "asset_id+event_type+time_window",
    },
]

# PBC-28 运维告警信号规则。前三条是计数阈值（停用即关闭对应信号）；后三条是参数
# 规则（threshold 即分钟数，停用/缺失回退默认值，不关闭信号本身）。检查逻辑在
# `app.services.jobs.ops_alerts`，此处只落可配置默认值，不写死业务逻辑。
DEFAULT_OPS_ALERT_RULES = [
    {
        "rule_name": "索引失败堆积告警",
        "severity": AlertSeverity.warning.value,
        "threshold": 5,
        "threshold_unit": "versions",
        "dedup_strategy": "signal+cooldown",
    },
    {
        "rule_name": "解析停滞堆积告警",
        "severity": AlertSeverity.warning.value,
        "threshold": 5,
        "threshold_unit": "versions",
        "dedup_strategy": "signal+cooldown",
    },
    {
        "rule_name": "登录安全异常告警",
        "severity": AlertSeverity.critical.value,
        "threshold": 10,
        "threshold_unit": "events",
        "dedup_strategy": "signal+cooldown",
    },
    {
        "rule_name": "解析停滞判定时长",
        "severity": AlertSeverity.warning.value,
        "threshold": 120,
        "threshold_unit": "minutes",
        "dedup_strategy": None,
    },
    {
        "rule_name": "登录安全统计时间窗",
        "severity": AlertSeverity.critical.value,
        "threshold": 15,
        "threshold_unit": "minutes",
        "dedup_strategy": None,
    },
    {
        "rule_name": "运维告警冷却期",
        "severity": AlertSeverity.warning.value,
        "threshold": 360,
        "threshold_unit": "minutes",
        "dedup_strategy": None,
    },
]


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"denied_reason": reason, "message": message}
    )


def _require_admin(caller: CallerContext) -> None:
    """Admin Alert API 仅 admin。"""
    if CompanyRole.admin.value not in caller.active_company_roles:
        raise _denied(403, "alert_admin_required", "仅 admin 可访问告警设置")


async def ensure_default_rules(session: AsyncSession) -> None:
    """幂等创建默认告警规则（归档阈值 + 运维信号；按 rule_name 去重）。"""
    for spec in DEFAULT_ARCHIVE_RULES + DEFAULT_OPS_ALERT_RULES:
        exists = (
            await session.execute(
                select(AlertRule.id).where(AlertRule.rule_name == spec["rule_name"])
            )
        ).scalar_one_or_none()
        if exists is None:
            session.add(
                AlertRule(
                    rule_name=spec["rule_name"],
                    severity=spec["severity"],
                    threshold=spec["threshold"],
                    threshold_unit=spec["threshold_unit"],
                    enabled=True,
                    notification_channels=[NotificationChannel.in_app.value],
                    dedup_strategy=spec["dedup_strategy"],
                )
            )
    await session.commit()


def _rule_out(rule: AlertRule) -> AlertRuleOut:
    return AlertRuleOut(
        id=rule.id,
        rule_name=rule.rule_name,
        severity=rule.severity,
        threshold=float(rule.threshold) if rule.threshold is not None else None,
        threshold_unit=rule.threshold_unit,
        enabled=rule.enabled,
        notification_channels=list(rule.notification_channels or []),
        dedup_strategy=rule.dedup_strategy,
        updated_at=rule.updated_at,
    )


async def list_rules(session: AsyncSession, caller: CallerContext) -> AlertRulesResponse:
    _require_admin(caller)
    await ensure_default_rules(session)
    rows = list(
        (await session.execute(select(AlertRule).order_by(AlertRule.created_at))).scalars().all()
    )
    return AlertRulesResponse(items=[_rule_out(r) for r in rows])


async def update_rule(
    session: AsyncSession,
    caller: CallerContext,
    rule_id: uuid.UUID,
    body: AlertRuleUpdateBody,
    trace_id: str,
) -> AlertRuleOut:
    """更新规则（enabled / threshold / notification_channels）。写 config.alert_rule_updated。"""
    _require_admin(caller)
    rule = (
        await session.execute(select(AlertRule).where(AlertRule.id == rule_id))
    ).scalar_one_or_none()
    if rule is None:
        raise _denied(404, "alert_rule_not_found", "告警规则不存在")

    before = {
        "enabled": rule.enabled,
        "threshold": float(rule.threshold) if rule.threshold is not None else None,
        "notification_channels": list(rule.notification_channels or []),
    }
    if body.enabled is not None:
        rule.enabled = body.enabled
    if body.threshold is not None:
        rule.threshold = body.threshold
    if body.notification_channels is not None:
        # 校验每个渠道为合法枚举（in_app / wecom / email）；未知值 → 422，不存任意串。
        valid = {c.value for c in NotificationChannel}
        invalid = [c for c in body.notification_channels if c not in valid]
        if invalid:
            raise _denied(
                422,
                "invalid_notification_channel",
                f"非法通知渠道：{invalid}（允许：{sorted(valid)}）",
            )
        rule.notification_channels = list(body.notification_channels)
    after = {
        "enabled": rule.enabled,
        "threshold": float(rule.threshold) if rule.threshold is not None else None,
        "notification_channels": list(rule.notification_channels or []),
    }

    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.config_alert_rule_updated.value,
        trace_id=trace_id,
        target_type="alert_rule",
        target_id=rule.id,
        before=before,
        after=after,
        extra={"rule_name": rule.rule_name},
    )
    await session.commit()
    return _rule_out(rule)


async def list_notifications(session: AsyncSession, caller: CallerContext) -> NotificationsResponse:
    """通知记录查询（admin）。只回安全元数据。"""
    _require_admin(caller)
    rows = list(
        (
            await session.execute(
                select(NotificationRecord).order_by(NotificationRecord.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    name_map: dict[uuid.UUID, str] = {}
    ids = {r.recipient_user_id for r in rows if r.recipient_user_id}
    if ids:
        name_rows = (
            await session.execute(select(User.id, User.name).where(User.id.in_(ids)))
        ).all()
        name_map = {r[0]: r[1] for r in name_rows}
    return NotificationsResponse(
        items=[
            NotificationOut(
                id=r.id,
                alert_rule_id=r.alert_rule_id,
                audit_event_id=r.audit_event_id,
                recipient_user_id=r.recipient_user_id,
                recipient_name=name_map.get(r.recipient_user_id),
                channel=r.channel,
                title=r.title,
                content=r.content,
                send_status=r.send_status,
                sent_at=r.sent_at,
                created_at=r.created_at,
            )
            for r in rows
        ]
    )


async def record_local_notification(
    session: AsyncSession,
    *,
    recipient_user_id: uuid.UUID,
    title: str,
    content: str,
    audit_event_id: uuid.UUID | None = None,
    channel: str = NotificationChannel.in_app.value,
    alert_rule_id: uuid.UUID | None = None,
) -> NotificationRecord:
    """新建一条本地站内通知记录（不发送）。只 add，不 commit（随业务事务提交）。

    调用方应保证 title / content 仅含安全元数据；此外本函数在写入前再做一道值级
    脱敏兜底（与审计同一口径），即便调用方误传对象存储 URL / 文件地址 / 内部地址等
    敏感串，也整串替换为占位符，绝不落库到 notification_records。保护当前生命周期
    调用方与未来所有通知写入方。
    """
    rec = NotificationRecord(
        recipient_user_id=recipient_user_id,
        audit_event_id=audit_event_id,
        alert_rule_id=alert_rule_id,
        channel=channel,
        title=audit_service.sanitize_text(title) or "",
        content=audit_service.sanitize_text(content) or "",
        send_status=NotificationStatus.pending.value,
    )
    session.add(rec)
    return rec

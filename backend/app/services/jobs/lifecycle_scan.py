"""生命周期归档预警/候选扫描作业（R5）。

按 `alert_rules` 阈值扫描 active 资产：
- 长期未调用 → 产生 `archive_warning`。
- 预警期已过仍未处理 → 产生 `archive_candidate`。

强约束：
- **绝不**把 asset_status 改为 archived——仅产生预警/候选信号，归档仍须人工 archive-confirm。
- 复用既有 `asset_lifecycle_events` / 审计 action / 本地 `notification_records`。
- 阈值取 `ensure_default_rules` 落库的规则；规则缺失/停用时回退默认值。
- 去重：按 asset + event_type + 时间窗口，避免重复扫描刷屏。
- 生命周期 reason / 通知文本沿用值级脱敏（经 record_local_notification + system 审计）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeAsset
from app.models.lifecycle import AlertRule, AssetLifecycleEvent
from app.schemas.enums import (
    AssetStatus,
    AuditAction,
    AuditLogType,
    LifecycleEventType,
    LifecycleTriggeredBy,
)
from app.services import alert as alert_service
from app.services import audit as audit_service

# 阈值回退默认值（与 alert.DEFAULT_ARCHIVE_RULES 一致；仅在规则缺失/停用时使用）。
_DEFAULT_INACTIVITY_DAYS = 730
_DEFAULT_WARNING_DAYS = 30
_RULE_INACTIVITY = "长期未调用归档预警"
_RULE_WARNING_PERIOD = "归档预警期"


def _to_naive_utc(dt: datetime) -> datetime:
    """统一为 naive UTC，规避 SQLite 取回 naive 与 aware now 相减报错。"""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


async def _rule_threshold(session: AsyncSession, rule_name: str, default: int) -> int:
    rule = (
        await session.execute(select(AlertRule).where(AlertRule.rule_name == rule_name))
    ).scalar_one_or_none()
    if rule is None or not rule.enabled or rule.threshold is None:
        return default
    return int(rule.threshold)


async def _latest_event_at(
    session: AsyncSession, asset_id: uuid.UUID, event_type: str
) -> datetime | None:
    row = (
        await session.execute(
            select(AssetLifecycleEvent.created_at)
            .where(AssetLifecycleEvent.asset_id == asset_id)
            .where(AssetLifecycleEvent.event_type == event_type)
            .order_by(AssetLifecycleEvent.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return _to_naive_utc(row) if row is not None else None


async def _emit(
    session: AsyncSession,
    asset: KnowledgeAsset,
    *,
    event_type: str,
    action: str,
    inactive_days: int,
    trace_id: str | None,
) -> None:
    """写一条系统生命周期事件 + 安全审计 + 本地通知（不改 asset_status）。"""
    reason = f"系统扫描：长期未调用 {inactive_days} 天"
    event = AssetLifecycleEvent(
        asset_id=asset.id, event_type=event_type,
        old_status=asset.asset_status, new_status=None,
        triggered_by=LifecycleTriggeredBy.system.value, actor_user_id=None,
        reason=audit_service.sanitize_text(reason), trace_id=trace_id,
    )
    session.add(event)
    await session.flush()
    audit_event = await audit_service.record_system_event(
        session, log_type=AuditLogType.operation, action=action, trace_id=trace_id or "",
        target_type="knowledge_asset", target_id=asset.id,
        extra={
            "event_type": event_type,
            "inactive_days": inactive_days,
            "scope": asset.scope,
            "lifecycle_event_id": str(event.id),
        },
    )
    await session.flush()
    recipient = asset.maintainer_user_id or asset.owner_user_id
    if recipient is not None:
        from app.services.wecom_notification import default_notification_channel

        await alert_service.record_local_notification(
            session,
            recipient_user_id=recipient,
            title=f"归档{'候选' if event_type == LifecycleEventType.archive_candidate.value else '预警'}：{asset.title}",
            content=f"资产「{asset.title}」（{asset.scope}）长期未调用（{inactive_days} 天），请评估是否归档。",
            audit_event_id=audit_event.id,
            channel=default_notification_channel(),
        )


async def scan_archive_candidates(
    session: AsyncSession,
    *,
    trace_id: str | None = None,
    now: datetime | None = None,
) -> dict:
    """扫描 active 资产产生归档预警/候选（去重，不改状态）。返回安全计数。"""
    await alert_service.ensure_default_rules(session)
    now_naive = _to_naive_utc(now or datetime.now(timezone.utc))
    inactivity_days = await _rule_threshold(session, _RULE_INACTIVITY, _DEFAULT_INACTIVITY_DAYS)
    warning_days = await _rule_threshold(session, _RULE_WARNING_PERIOD, _DEFAULT_WARNING_DAYS)

    assets = list(
        (
            await session.execute(
                select(KnowledgeAsset).where(
                    KnowledgeAsset.asset_status == AssetStatus.active.value
                )
            )
        ).scalars().all()
    )

    warnings = candidates = 0
    for asset in assets:
        last = asset.last_called_at or asset.created_at
        if last is None:
            continue
        inactive_days = (now_naive - _to_naive_utc(last)).days
        if inactive_days < inactivity_days:
            continue

        last_warning = await _latest_event_at(
            session, asset.id, LifecycleEventType.archive_warning.value
        )
        if last_warning is None:
            # 首次预警。
            await _emit(
                session, asset,
                event_type=LifecycleEventType.archive_warning.value,
                action=AuditAction.lifecycle_archive_warning.value,
                inactive_days=inactive_days, trace_id=trace_id,
            )
            warnings += 1
            continue

        # 已预警：预警期已过且尚无（更新的）候选 → 升级为候选（去重）。
        warning_age = (now_naive - last_warning).days
        if warning_age >= warning_days:
            last_candidate = await _latest_event_at(
                session, asset.id, LifecycleEventType.archive_candidate.value
            )
            if last_candidate is None or last_candidate < last_warning:
                await _emit(
                    session, asset,
                    event_type=LifecycleEventType.archive_candidate.value,
                    action=AuditAction.lifecycle_archive_candidate.value,
                    inactive_days=inactive_days, trace_id=trace_id,
                )
                candidates += 1
        # 预警期内重复扫描 → 去重跳过。

    await session.commit()
    return {"warnings": warnings, "candidates": candidates, "scanned": len(assets)}

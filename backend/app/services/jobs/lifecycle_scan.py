"""生命周期归档预警/候选扫描作业。

按 `alert_rules` 阈值扫描 active 资产：
- 长期未调用 → 产生 `archive_warning`。
- 预警期已过仍未处理 → 产生 `archive_candidate`。

强约束：
- **绝不**把 asset_status 改为 archived——仅产生预警/候选信号，归档仍须人工 archive-confirm。
- 复用既有 `asset_lifecycle_events` / 审计 action / 本地 `notification_records`。
- 阈值取 `ensure_default_rules` 落库的规则；规则缺失/停用时回退默认值。
- 去重：按 asset + event_type + 时间窗口，避免重复扫描刷屏。
- 生命周期 reason / 通知文本沿用值级脱敏（经 Outbox 消费端 + system 审计）。
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
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
from app.services import operation_events
from app.services.jobs import governance_scan
from app.worker.enqueue import enqueue_outbox_delivery

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


async def _emit(
    session: AsyncSession,
    asset: KnowledgeAsset,
    *,
    event_type: str,
    action: str,
    inactive_days: int,
    trace_id: str | None,
) -> None:
    """写系统生命周期事件、审计和同事务通知事件（不改 asset_status）。"""
    reason = f"系统扫描：长期未调用 {inactive_days} 天"
    event = AssetLifecycleEvent(
        asset_id=asset.id,
        event_type=event_type,
        old_status=asset.asset_status,
        new_status=None,
        triggered_by=LifecycleTriggeredBy.system.value,
        actor_user_id=None,
        reason=audit_service.sanitize_text(reason),
        trace_id=trace_id,
    )
    session.add(event)
    await session.flush()
    audit_event = await audit_service.record_system_event(
        session,
        log_type=AuditLogType.operation,
        action=action,
        trace_id=trace_id or "",
        target_type="knowledge_asset",
        target_id=asset.id,
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
        notice_type = (
            "lifecycle_archive_candidate"
            if event_type == LifecycleEventType.archive_candidate.value
            else "lifecycle_archive_warning"
        )
        await operation_events.publish_local_notification(
            session,
            notice_type=notice_type,
            recipient_id=recipient,
            asset_id=asset.id,
            audit_event_id=audit_event.id,
        )


async def scan_archive_candidates(
    session: AsyncSession,
    *,
    trace_id: str | None = None,
    now: datetime | None = None,
    resume_only: bool = False,
) -> dict:
    """Process one bounded batch; later tasks resume the durable daily cycle."""
    started = time.monotonic()
    run = await governance_scan.begin_cycle(session, "archive", resume_only=resume_only, now=now)
    if run is None:
        return {"warnings": 0, "candidates": 0, "scanned": 0}
    try:
        if not run.parameters:
            await alert_service.ensure_default_rules(session, commit=False)
            run.parameters = {
                "inactivity_days": await _rule_threshold(
                    session, _RULE_INACTIVITY, _DEFAULT_INACTIVITY_DAYS
                ),
                "warning_days": await _rule_threshold(
                    session, _RULE_WARNING_PERIOD, _DEFAULT_WARNING_DAYS
                ),
            }
        inactivity_days = run.parameters["inactivity_days"]
        warning_days = run.parameters["warning_days"]
        now_naive = _to_naive_utc(run.cutoff_at)
        conditions = (
            KnowledgeAsset.asset_status == AssetStatus.active.value,
            func.coalesce(KnowledgeAsset.last_called_at, KnowledgeAsset.created_at)
            <= run.cutoff_at - timedelta(days=inactivity_days),
        )
        assets = await governance_scan.claim_assets(session, run, *conditions)
        latest = {}
        if assets:
            rows = (
                await session.execute(
                    select(
                        AssetLifecycleEvent.asset_id,
                        AssetLifecycleEvent.event_type,
                        func.max(AssetLifecycleEvent.created_at),
                    )
                    .where(
                        AssetLifecycleEvent.asset_id.in_([asset.id for asset in assets]),
                        AssetLifecycleEvent.event_type.in_(
                            ["archive_warning", "archive_candidate"]
                        ),
                    )
                    .group_by(AssetLifecycleEvent.asset_id, AssetLifecycleEvent.event_type)
                )
            ).all()
            latest = {(asset_id, kind): _to_naive_utc(at) for asset_id, kind, at in rows}
        warnings = candidates = 0
        processed: list[uuid.UUID] = []
        for asset in assets:
            if governance_scan.budget_exhausted(started, processed):
                break
            inactive_days = (
                now_naive - _to_naive_utc(asset.last_called_at or asset.created_at)
            ).days
            last_warning = latest.get((asset.id, "archive_warning"))
            last_candidate = latest.get((asset.id, "archive_candidate"))
            if last_warning is None:
                await _emit(
                    session,
                    asset,
                    event_type=LifecycleEventType.archive_warning.value,
                    action=AuditAction.lifecycle_archive_warning.value,
                    inactive_days=inactive_days,
                    trace_id=trace_id,
                )
                warnings += 1
            elif (now_naive - last_warning).days >= warning_days and (
                last_candidate is None or last_candidate < last_warning
            ):
                await _emit(
                    session,
                    asset,
                    event_type=LifecycleEventType.archive_candidate.value,
                    action=AuditAction.lifecycle_archive_candidate.value,
                    inactive_days=inactive_days,
                    trace_id=trace_id,
                )
                candidates += 1
            processed.append(asset.id)
        await governance_scan.finish_batch(session, run, processed, *conditions)
    except BaseException:
        # Cancellation must roll back the current events AND their watermarks.
        await session.rollback()
        raise
    if warnings or candidates:
        await enqueue_outbox_delivery(session)
    return {"warnings": warnings, "candidates": candidates, "scanned": len(processed)}

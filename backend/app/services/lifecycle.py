"""知识资产生命周期治理服务。

落实 BE-10 / 契约 §14A：
- 系统/人只产生预警/候选（request），归档与重新启用必须人工确认（confirm）。
- 归档不删除：只改治理状态 + 追加 asset_lifecycle_events 事实 + 审计 + 本地通知。
- 权限：纯 admin 一律拒绝并强审计 admin.business_denied；按 scope 治理角色授权
  （personal 本人 / project maintainer·PM / company boss·咨询总监）；不可见资产
  （他人个人 / 无权 L5）一律表现为不存在，不泄露。
- 所有权限判断复用集中 `app.services.permission` 的 lifecycle_* 函数，不在此重写矩阵。
- L5 / A4 / 公司级的确认动作强审计（severity + extra.risk_level）。
- trace_id 贯穿：生命周期事件 / 审计事件 / 通知共享同一 trace_id。

边界：不实现定时扫描、审批流引擎、真实通知发送、向量过滤、物理清理（见 BE-10 §14）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import User
from app.models.knowledge import KnowledgeAsset
from app.models.lifecycle import AssetLifecycleEvent
from app.schemas.enums import (
    AlertSeverity,
    AssetStatus,
    AuditAction,
    AuditLogType,
    AuditRiskLevel,
    LifecycleEventType,
    LifecycleTriggeredBy,
)
from app.schemas.lifecycle import (
    ArchiveConfirmBody,
    ArchiveConfirmResponse,
    ArchiveRequestBody,
    LifecycleActionResponse,
    LifecycleEventOut,
    LifecycleEventsResponse,
    ReenableConfirmBody,
    ReenableConfirmResponse,
    ReenableRequestBody,
)
from app.schemas.permission import CallerContext, DeniedReason
from app.services import alert as alert_service
from app.services import audit as audit_service
from app.services.permission import (
    lifecycle_actor_allowed,
    lifecycle_is_strong_audit,
    lifecycle_visibility,
)

# 重新启用允许的目标状态。
_REENABLE_TARGETS = {AssetStatus.active.value, AssetStatus.needs_update.value}
# 可被归档确认的起始状态（archived 不可再次归档）。
_ARCHIVABLE_FROM = {
    AssetStatus.active.value,
    AssetStatus.needs_update.value,
    AssetStatus.deprecated.value,
}


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"denied_reason": reason, "message": message}
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _load_governable_asset(
    session: AsyncSession,
    caller: CallerContext,
    asset_id: uuid.UUID,
    *,
    trace_id: str,
    attempted: str,
    require_actor: bool,
) -> KnowledgeAsset:
    """加载资产并完成生命周期治理的统一权限闸门。

    顺序（与 preview/agent 一致，避免泄露）：
    1. 纯 admin / 非业务用户 → admin.business_denied（强审计）+ 403。
    2. 资产不存在 / 不可见（他人个人 / 无权 L5）→ 404，不泄露存在性。
    3. require_actor 时校验是否为合法治理动作人 → 403 lifecycle_action_not_allowed。
    """
    if not caller.is_business_user:
        await audit_service.record_denied(
            session, caller=caller, log_type=AuditLogType.exception,
            action=AuditAction.admin_business_denied.value, trace_id=trace_id,
            target_type="knowledge_asset", target_id=asset_id,
            severity=AlertSeverity.warning, risk_level=AuditRiskLevel.high.value,
            extra={"denied_reason": "admin_business_permission_denied", "attempted": attempted},
        )
        raise _denied(403, "admin_business_permission_denied", "admin 不拥有业务生命周期治理权")

    asset = (
        await session.execute(select(KnowledgeAsset).where(KnowledgeAsset.id == asset_id))
    ).scalar_one_or_none()
    not_found = _denied(404, "knowledge_asset_not_found", "知识资产不存在或不可见")
    if asset is None:
        raise not_found

    vis = lifecycle_visibility(caller, asset)
    if vis is not None:
        if vis == DeniedReason.user_inactive:
            raise _denied(403, DeniedReason.user_inactive.value, "用户已停用")
        # l5_not_discoverable / personal_asset_not_owned 一律表现为不存在。
        raise not_found

    if require_actor and not lifecycle_actor_allowed(caller, asset):
        raise _denied(
            403, "lifecycle_action_not_allowed", "当前身份无该资产的生命周期治理动作权"
        )
    return asset


async def _notify(
    session: AsyncSession,
    asset: KnowledgeAsset,
    *,
    title: str,
    content: str,
    audit_event_id: uuid.UUID | None,
) -> None:
    """对资产维护人 / 所有者发一条本地站内通知（安全元数据）。"""
    recipient = asset.maintainer_user_id or asset.owner_user_id
    if recipient is None:
        return
    from app.services.wecom_notification import default_notification_channel

    await alert_service.record_local_notification(
        session,
        recipient_user_id=recipient,
        title=title,
        content=content,
        audit_event_id=audit_event_id,
        channel=default_notification_channel(),
    )


# ============================================================
# 发起归档建议（不改状态）
# ============================================================
async def archive_request(
    session: AsyncSession,
    caller: CallerContext,
    asset_id: uuid.UUID,
    body: ArchiveRequestBody,
    trace_id: str,
) -> LifecycleActionResponse:
    asset = await _load_governable_asset(
        session, caller, asset_id, trace_id=trace_id,
        attempted="lifecycle.archive_request", require_actor=True,
    )
    if asset.asset_status == AssetStatus.archived.value:
        raise _denied(409, "lifecycle_invalid_transition", "资产已归档，无需再次发起归档")

    # 写入时对用户文本做值级脱敏（防止经 reason 把对象存储 / 内部地址等落库）。
    reason = audit_service.sanitize_text(body.reason)

    # 有候选来源 → archive_candidate；否则按预警 archive_warning。
    if body.candidate_source:
        event_type = LifecycleEventType.archive_candidate.value
        action = AuditAction.lifecycle_archive_candidate.value
    else:
        event_type = LifecycleEventType.archive_warning.value
        action = AuditAction.lifecycle_archive_warning.value

    event = AssetLifecycleEvent(
        asset_id=asset.id, event_type=event_type,
        old_status=asset.asset_status, new_status=None,
        triggered_by=LifecycleTriggeredBy.user.value, actor_user_id=caller.user_id,
        reason=reason, trace_id=trace_id,
    )
    session.add(event)
    await session.flush()

    await audit_service.record_event(
        session, caller=caller, log_type=AuditLogType.operation,
        action=action, trace_id=trace_id,
        target_type="knowledge_asset", target_id=asset.id,
        extra={
            "event_type": event_type,
            "candidate_source": body.candidate_source,
            "lifecycle_event_id": str(event.id),
        },
        project_id=asset.project_id,
    )
    await session.commit()
    return LifecycleActionResponse(
        lifecycle_event_id=event.id, review_task_id=None, status=event_type, trace_id=trace_id
    )


# ============================================================
# 确认归档（改状态 → archived）
# ============================================================
async def archive_confirm(
    session: AsyncSession,
    caller: CallerContext,
    asset_id: uuid.UUID,
    body: ArchiveConfirmBody,
    trace_id: str,
) -> ArchiveConfirmResponse:
    asset = await _load_governable_asset(
        session, caller, asset_id, trace_id=trace_id,
        attempted="lifecycle.archive_confirm", require_actor=True,
    )
    if asset.asset_status not in _ARCHIVABLE_FROM:
        raise _denied(
            409, "lifecycle_invalid_transition",
            f"当前状态 {asset.asset_status} 不可确认归档",
        )

    reason = audit_service.sanitize_text(body.reason)
    old_status = asset.asset_status
    asset.asset_status = AssetStatus.archived.value
    asset.archived_at = _now()
    asset.archive_reason = reason

    event = AssetLifecycleEvent(
        asset_id=asset.id, event_type=LifecycleEventType.archived.value,
        old_status=old_status, new_status=AssetStatus.archived.value,
        triggered_by=LifecycleTriggeredBy.user.value, actor_user_id=caller.user_id,
        reason=reason, review_task_id=body.review_task_id, trace_id=trace_id,
    )
    session.add(event)
    await session.flush()

    strong = lifecycle_is_strong_audit(asset)
    audit_event = await audit_service.record_event(
        session, caller=caller, log_type=AuditLogType.operation,
        action=AuditAction.lifecycle_archived.value, trace_id=trace_id,
        target_type="knowledge_asset", target_id=asset.id,
        before={"asset_status": old_status},
        after={"asset_status": asset.asset_status},
        severity=AlertSeverity.warning if strong else None,
        risk_level=AuditRiskLevel.high.value if strong else None,
        extra={
            "scope": asset.scope,
            "confidentiality_level": asset.confidentiality_level,
            "ai_access_level": asset.ai_access_level,
            "lifecycle_event_id": str(event.id),
        },
        project_id=asset.project_id,
    )
    await session.flush()
    await _notify(
        session, asset,
        title=f"知识资产已归档：{asset.title}",
        content=(
            f"资产「{asset.title}」（{asset.scope}/{asset.confidentiality_level}）"
            f"已由 {old_status} 归档。原因：{reason}。"
        ),
        audit_event_id=audit_event.id,
    )
    await session.commit()
    return ArchiveConfirmResponse(
        asset_id=asset.id,
        asset_status=asset.asset_status,
        archived_at=asset.archived_at,
        archive_reason=asset.archive_reason,
        trace_id=trace_id,
    )


# ============================================================
# 发起重新启用（不改状态）
# ============================================================
async def reenable_request(
    session: AsyncSession,
    caller: CallerContext,
    asset_id: uuid.UUID,
    body: ReenableRequestBody,
    trace_id: str,
) -> LifecycleActionResponse:
    asset = await _load_governable_asset(
        session, caller, asset_id, trace_id=trace_id,
        attempted="lifecycle.reenable_request", require_actor=True,
    )
    if asset.asset_status != AssetStatus.archived.value:
        raise _denied(
            409, "lifecycle_invalid_transition", "仅已归档资产可发起重新启用"
        )

    event = AssetLifecycleEvent(
        asset_id=asset.id, event_type=LifecycleEventType.reenable_requested.value,
        old_status=asset.asset_status, new_status=None,
        triggered_by=LifecycleTriggeredBy.user.value, actor_user_id=caller.user_id,
        reason=audit_service.sanitize_text(body.reason), trace_id=trace_id,
    )
    session.add(event)
    await session.flush()

    await audit_service.record_event(
        session, caller=caller, log_type=AuditLogType.operation,
        action=AuditAction.lifecycle_reenable_requested.value, trace_id=trace_id,
        target_type="knowledge_asset", target_id=asset.id,
        extra={
            "target_status": body.target_status,
            "lifecycle_event_id": str(event.id),
        },
        project_id=asset.project_id,
    )
    await session.commit()
    return LifecycleActionResponse(
        lifecycle_event_id=event.id, review_task_id=None,
        status=LifecycleEventType.reenable_requested.value, trace_id=trace_id,
    )


# ============================================================
# 确认重新启用（改状态 → active / needs_update）
# ============================================================
async def reenable_confirm(
    session: AsyncSession,
    caller: CallerContext,
    asset_id: uuid.UUID,
    body: ReenableConfirmBody,
    trace_id: str,
) -> ReenableConfirmResponse:
    if body.target_status not in _REENABLE_TARGETS:
        raise _denied(
            422, "lifecycle_invalid_target_status",
            "target_status 仅允许 active 或 needs_update",
        )
    asset = await _load_governable_asset(
        session, caller, asset_id, trace_id=trace_id,
        attempted="lifecycle.reenable_confirm", require_actor=True,
    )
    if asset.asset_status != AssetStatus.archived.value:
        raise _denied(
            409, "lifecycle_invalid_transition", "仅已归档资产可确认重新启用"
        )

    reason = audit_service.sanitize_text(body.reason)
    old_status = asset.asset_status
    asset.asset_status = body.target_status
    # 保留 archived_at / archive_reason 作为历史追溯（不清空，BE-10 §6.3）。

    event = AssetLifecycleEvent(
        asset_id=asset.id, event_type=LifecycleEventType.reenabled.value,
        old_status=old_status, new_status=body.target_status,
        triggered_by=LifecycleTriggeredBy.user.value, actor_user_id=caller.user_id,
        reason=reason, review_task_id=body.review_task_id, trace_id=trace_id,
    )
    session.add(event)
    await session.flush()

    strong = lifecycle_is_strong_audit(asset)
    audit_event = await audit_service.record_event(
        session, caller=caller, log_type=AuditLogType.operation,
        action=AuditAction.lifecycle_reenabled.value, trace_id=trace_id,
        target_type="knowledge_asset", target_id=asset.id,
        before={"asset_status": old_status},
        after={"asset_status": asset.asset_status},
        severity=AlertSeverity.warning if strong else None,
        risk_level=AuditRiskLevel.high.value if strong else None,
        extra={
            "scope": asset.scope,
            "confidentiality_level": asset.confidentiality_level,
            "ai_access_level": asset.ai_access_level,
            "lifecycle_event_id": str(event.id),
            "archived_at_retained": asset.archived_at.isoformat() if asset.archived_at else None,
        },
        project_id=asset.project_id,
    )
    await session.flush()
    await _notify(
        session, asset,
        title=f"知识资产已重新启用：{asset.title}",
        content=(
            f"资产「{asset.title}」已重新启用为 {body.target_status}（曾归档，"
            f"归档记录保留用于追溯）。原因：{reason}。"
        ),
        audit_event_id=audit_event.id,
    )
    await session.commit()
    return ReenableConfirmResponse(
        asset_id=asset.id,
        asset_status=asset.asset_status,
        lifecycle_event_id=event.id,
        trace_id=trace_id,
    )


# ============================================================
# 查询生命周期事件（按可见性，不泄露 L5 存在）
# ============================================================
async def list_events(
    session: AsyncSession, caller: CallerContext, asset_id: uuid.UUID
) -> LifecycleEventsResponse:
    """查询单个资产的生命周期事件。可见性与知识详情一致（含 archived 资产可查），
    但他人个人 / 无权 L5 一律表现为不存在。普通用户无全局查询权（仅按资产可见性）。"""
    asset = (
        await session.execute(select(KnowledgeAsset).where(KnowledgeAsset.id == asset_id))
    ).scalar_one_or_none()
    not_found = _denied(404, "knowledge_asset_not_found", "知识资产不存在或不可见")
    if asset is None:
        raise not_found
    vis = lifecycle_visibility(caller, asset)
    if vis is not None:
        if vis == DeniedReason.user_inactive:
            raise _denied(403, DeniedReason.user_inactive.value, "用户已停用")
        raise not_found

    rows = list(
        (
            await session.execute(
                select(AssetLifecycleEvent)
                .where(AssetLifecycleEvent.asset_id == asset_id)
                .order_by(AssetLifecycleEvent.created_at)
            )
        )
        .scalars()
        .all()
    )
    actor_ids = {e.actor_user_id for e in rows if e.actor_user_id}
    names: dict[uuid.UUID, str] = {}
    if actor_ids:
        name_rows = (
            await session.execute(select(User.id, User.name).where(User.id.in_(actor_ids)))
        ).all()
        names = {r[0]: r[1] for r in name_rows}

    return LifecycleEventsResponse(
        items=[
            LifecycleEventOut(
                event_id=e.id,
                event_type=e.event_type,
                old_status=e.old_status,
                new_status=e.new_status,
                reason=e.reason,
                actor_display=names.get(e.actor_user_id) if e.actor_user_id else None,
                created_at=e.created_at,
                trace_id=e.trace_id,
            )
            for e in rows
        ]
    )


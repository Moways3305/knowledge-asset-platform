"""跨项目复用统计 + 升格推荐作业（R5）。

从既有后端事实（`agent_call_citations` join `agent_calls.project_id`）计算安全复用信号：
- 回写 `knowledge_assets.last_called_at`（被引用/使用即更新）。
- 识别被多个项目复用、或调用次数超阈值的 **project** 资产。
- 对这类资产推一条**人审升格推荐**（通知 Boss / 咨询总监 + 安全审计事件）。

强约束：
- **绝不**自动升格 scope/zone——只产生候选信号，升格仍须 Boss / 咨询总监审核。
- 去重：同一资产已推过（存在 knowledge.upgrade_recommended 审计事件）则不再重复推。

设计取舍（见报告）：本作业**只发本地通知 + 审计推荐事件**，不创建 `project_to_company`
ReviewTask——现有审核流approve/reject 仅实现 material_to_asset 语义，
新建 project_to_company 任务需扩展审批流（属本票 Non-Scope）。后续接审批流的明确步骤：
在 review 服务补 project_to_company 的 approve 处理（material→asset 之外的 scope 升格），
再把本作业的推荐产物从"通知+审计"替换/补充为 ReviewTask 创建。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentCall, AgentCallCitation
from app.models.audit import AuditEvent
from app.models.identity import UserCompanyRole
from app.models.knowledge import KnowledgeAsset
from app.schemas.enums import (
    AssetStatus,
    AuditAction,
    AuditLogType,
    CompanyRole,
    KnowledgeScope,
)
from app.services import alert as alert_service
from app.services import audit as audit_service

_DEFAULT_MIN_PROJECTS = 2  # 被 >=2 个项目复用
_DEFAULT_MIN_CALLS = 3  # 或调用次数 >= 3


def _to_naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


async def _governance_recipients(session: AsyncSession) -> list[uuid.UUID]:
    """active Boss / 咨询总监 用户 id（升格推荐接收人）。"""
    rows = (
        await session.execute(
            select(UserCompanyRole.user_id)
            .where(
                UserCompanyRole.company_role.in_(
                    [CompanyRole.boss.value, CompanyRole.consulting_director.value]
                )
            )
            .where(UserCompanyRole.status == "active")
        )
    ).all()
    return list({r[0] for r in rows})


async def _already_recommended(session: AsyncSession, asset_id: uuid.UUID) -> bool:
    row = (
        await session.execute(
            select(AuditEvent.id)
            .where(AuditEvent.action == AuditAction.knowledge_upgrade_recommended.value)
            .where(AuditEvent.target_id == asset_id)
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def scan_reuse_and_recommend(
    session: AsyncSession,
    *,
    trace_id: str | None = None,
    min_projects: int = _DEFAULT_MIN_PROJECTS,
    min_calls: int = _DEFAULT_MIN_CALLS,
) -> dict:
    """计算复用信号、回写 last_called_at、对合格 project 资产推一条升格推荐。返回安全计数。"""
    # 聚合：每个被引用资产的 最近使用时间 / 调用次数 / 去重项目数。
    rows = (
        await session.execute(
            select(
                AgentCallCitation.cited_asset_id,
                func.max(AgentCall.created_at),
                func.count(AgentCallCitation.id),
                func.count(func.distinct(AgentCall.project_id)),
            )
            .join(AgentCall, AgentCall.id == AgentCallCitation.call_id)
            .group_by(AgentCallCitation.cited_asset_id)
        )
    ).all()

    recipients = await _governance_recipients(session)
    updated = recommended = 0
    for asset_id, last_used, call_count, project_count in rows:
        asset = await session.get(KnowledgeAsset, asset_id)
        if asset is None:
            continue
        # 回写 last_called_at（取更晚者）。
        if last_used is not None:
            lu = _to_naive_utc(last_used)
            cur = _to_naive_utc(asset.last_called_at) if asset.last_called_at else None
            if cur is None or lu > cur:
                asset.last_called_at = last_used
                updated += 1

        # 仅 active project 资产、达到复用阈值、且未推过 → 推一条人审升格推荐。
        qualifies = (project_count >= min_projects) or (call_count >= min_calls)
        if (
            asset.scope == KnowledgeScope.project.value
            and asset.asset_status == AssetStatus.active.value
            and qualifies
            and not await _already_recommended(session, asset.id)
        ):
            audit_event = await audit_service.record_system_event(
                session, log_type=AuditLogType.operation,
                action=AuditAction.knowledge_upgrade_recommended.value, trace_id=trace_id or "",
                target_type="knowledge_asset", target_id=asset.id,
                extra={
                    "scope": asset.scope,
                    "reuse_project_count": int(project_count),
                    "reuse_call_count": int(call_count),
                    "recommendation": "project_to_company",
                },
            )
            await session.flush()
            from app.services.wecom_notification import default_notification_channel

            channel = default_notification_channel()
            for uid in recipients:
                await alert_service.record_local_notification(
                    session,
                    recipient_user_id=uid,
                    title=f"升格推荐：{asset.title}",
                    content=(
                        f"项目资产「{asset.title}」被 {int(project_count)} 个项目、共 "
                        f"{int(call_count)} 次复用，建议评估升格为公司知识资产"
                        f"（需 Boss / 咨询总监审核，系统不自动升格）。"
                    ),
                    audit_event_id=audit_event.id,
                    channel=channel,
                )
            recommended += 1

    await session.commit()
    return {"usage_updated": updated, "recommended": recommended, "assets": len(rows)}


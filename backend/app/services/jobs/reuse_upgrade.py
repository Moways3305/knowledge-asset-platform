"""跨项目复用统计 + 升格推荐作业。

从既有后端事实（`agent_call_citations` join `agent_calls.project_id`）计算安全复用信号：
- 回写 `knowledge_assets.last_called_at`（被引用/使用即更新）。
- 识别被多个项目复用、或调用次数超阈值的 **project** 资产。
- 对这类资产推一条**人审升格推荐**（通知总经理 / 咨询总监 + 安全审计事件）。

强约束：
- **绝不**自动升格 scope/zone——只产生候选信号，升格仍须总经理 / 咨询总监审核。
- 去重：同一资产已推过（存在 knowledge.upgrade_recommended 审计事件）则不再重复推。

设计取舍：本作业**只发本地通知 + 审计推荐事件**，不创建 `project_to_company`
ReviewTask——现有审核流 approve/reject 仅实现 material_to_asset 语义，
新建 project_to_company 任务需扩展审批流（当前不包含）。接审批流时的明确步骤：
在 review 服务补 project_to_company 的 approve 处理（material→asset 之外的 scope 升格），
再把本作业的推荐产物从"通知+审计"替换/补充为 ReviewTask 创建。
"""

from __future__ import annotations

import time
import uuid

from sqlalchemy import func, or_, select, update
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
from app.services import audit as audit_service
from app.services import operation_events
from app.services.jobs import governance_scan
from app.worker.enqueue import enqueue_outbox_delivery

_DEFAULT_MIN_PROJECTS = 2  # 被 >=2 个项目复用
_DEFAULT_MIN_CALLS = 3  # 或调用次数 >= 3


async def _governance_recipients(session: AsyncSession) -> list[uuid.UUID]:
    """active 总经理 / 咨询总监用户 id（升格推荐接收人）。"""
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


async def scan_reuse_and_recommend(
    session: AsyncSession,
    *,
    trace_id: str | None = None,
    min_projects: int = _DEFAULT_MIN_PROJECTS,
    min_calls: int = _DEFAULT_MIN_CALLS,
    resume_only: bool = False,
) -> dict:
    """One bounded batch; usage, recommendations and progress commit together.

    Count citation rows (the existing threshold rule), not distinct calls. Both
    calls and citations newer than the cycle cutoff wait for the next cycle.
    Assets remain locked through the recommendation check and durable writes.
    """
    started = time.monotonic()
    counts = {"usage_updated": 0, "recommended": 0, "assets": 0}
    try:
        run = await governance_scan.begin_cycle(session, "reuse", resume_only=resume_only)
        if run is None:
            return counts
        if not run.parameters:
            run.parameters = {"min_projects": min_projects, "min_calls": min_calls}
        min_projects = run.parameters["min_projects"]
        min_calls = run.parameters["min_calls"]
        citation_scope = (
            AgentCallCitation.created_at <= run.cutoff_at,
            AgentCall.created_at <= run.cutoff_at,
        )
        has_citations = (
            select(AgentCallCitation.id)
            .join(AgentCall, AgentCall.id == AgentCallCitation.call_id)
            .where(AgentCallCitation.cited_asset_id == KnowledgeAsset.id, *citation_scope)
            .exists()
        )
        assets = await governance_scan.claim_assets(session, run, has_citations)
        ids = [asset.id for asset in assets]
        if not ids:
            await governance_scan.finish_batch(session, run, [], has_citations)
            return counts
        # Restrict the input before GROUP BY, rather than grouping all history
        # and applying LIMIT afterwards. The asset/date/call index serves both
        # this aggregation and the correlated candidate EXISTS.
        aggregates = (
            select(
                AgentCallCitation.cited_asset_id.label("asset_id"),
                func.max(AgentCall.created_at).label("last_used"),
                func.count(AgentCallCitation.id).label("call_count"),
                func.count(func.distinct(AgentCall.project_id)).label("project_count"),
            )
            .join(AgentCall, AgentCall.id == AgentCallCitation.call_id)
            .where(AgentCallCitation.cited_asset_id.in_(ids), *citation_scope)
            .group_by(AgentCallCitation.cited_asset_id)
        ).subquery()
        stats = {row.asset_id: row for row in (await session.execute(select(aggregates))).all()}
        already = set(
            await session.scalars(
                select(AuditEvent.target_id).where(
                    AuditEvent.action == AuditAction.knowledge_upgrade_recommended.value,
                    AuditEvent.target_id.in_(ids),
                )
            )
        )
        recipients = await _governance_recipients(session)
        processed: list[uuid.UUID] = []
        for asset in assets:
            if governance_scan.budget_exhausted(started, processed):
                break
            row = stats.get(asset.id)
            qualifies = row is not None and (
                row.project_count >= min_projects or row.call_count >= min_calls
            )
            if (
                row is not None
                and qualifies
                and asset.id not in already
                and asset.scope == KnowledgeScope.project.value
                and asset.asset_status == AssetStatus.active.value
            ):
                audit_event = await audit_service.record_system_event(
                    session,
                    log_type=AuditLogType.operation,
                    action=AuditAction.knowledge_upgrade_recommended.value,
                    trace_id=trace_id or "",
                    target_type="knowledge_asset",
                    target_id=asset.id,
                    extra={
                        "scope": asset.scope,
                        "reuse_project_count": int(row.project_count),
                        "reuse_call_count": int(row.call_count),
                        "recommendation": "project_to_company",
                    },
                )
                await session.flush()
                for uid in recipients:
                    await operation_events.publish_local_notification(
                        session,
                        notice_type="reuse_upgrade",
                        recipient_id=uid,
                        asset_id=asset.id,
                        audit_event_id=audit_event.id,
                    )
                counts["recommended"] += 1
            processed.append(asset.id)
        # Update the processed batch in one statement. Preserve the database's
        # content baseline and never move usage backwards, even with stale ORM
        # state. No remote operation occurs while these asset locks are held.
        changed = await session.scalars(
            update(KnowledgeAsset)
            .where(
                KnowledgeAsset.id.in_(processed),
                KnowledgeAsset.id == aggregates.c.asset_id,
                or_(
                    KnowledgeAsset.last_called_at.is_(None),
                    KnowledgeAsset.last_called_at < aggregates.c.last_used,
                ),
            )
            .values(last_called_at=aggregates.c.last_used, updated_at=KnowledgeAsset.updated_at)
            .returning(KnowledgeAsset.id)
            .execution_options(synchronize_session=False)
        )
        counts["usage_updated"] = len(changed.all())
        counts["assets"] = len(processed)
        await governance_scan.finish_batch(session, run, processed, has_citations)
    except BaseException:
        await session.rollback()
        raise
    if counts["recommended"]:
        await enqueue_outbox_delivery(session)
    return counts

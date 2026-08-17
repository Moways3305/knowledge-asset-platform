"""Knowledge 运营洞察服务。

把 `/knowledge` 右侧的本地规则洞察升级为**真实后端安全聚合**。统计全部来自真实表
（knowledge_asset_versions / indexing_operation_jobs / weknora_kb_mappings /
original_access_requests / access_grants / asset_lifecycle_events / audit_events），
不再是前端本地规则，也不用假数字。

权限与可见边界：
- 未登录 / inactive → 403。
- 纯 admin（系统运维，非业务用户）：可看系统运维聚合，但 `title_visible=false`，
  recent_items 不含标题 / owner / 文件名。
- 总经理 / 咨询总监（治理）：可看公司范围、本人与 active 成员项目的聚合和安全下钻。
- 项目经理 / coach / 普通业务用户：限本人资产 + 所在项目资产范围聚合 + drilldown。
- insights 不绕过 `/knowledge` 发现权限：他人个人知识不计入、不下钻。

安全红线：响应**绝不**含 weknora kb/doc id、storage/source ref、download URL、token/cookie/
api_key、provider 内部 id、文件名、原文 / chunk 原文——这些只作 server-only 查询条件。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import denied
from app.db.utils import utc_now
from app.models.audit import AuditEvent
from app.models.identity import Project
from app.models.indexing_job import IndexingOperationJob
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.lifecycle import AssetLifecycleEvent
from app.models.original_access import OriginalAccessRequest
from app.models.weknora import WeknoraKbMapping
from app.schemas.enums import (
    AssetStatus,
    AuditAction,
    CompanyRole,
    KnowledgeScope,
    LifecycleEventType,
)
from app.schemas.knowledge_insights import (
    AccessInsights,
    IndexingInsights,
    InsightCard,
    InsightJobItem,
    InsightRecentItem,
    KnowledgeOpsInsightsResponse,
    LifecycleInsights,
    Recommendation,
)
from app.schemas.permission import CallerContext
from app.services import error_catalog
from app.services.permission_rules import access_request_timeout_hours

_ACTIVE_VERSION = "active"
_INDEXED = "indexed"
# 发现层不可见的资产终态：与 /knowledge 列表 / 详情 / 检索一致。
# permission.decide() 对 archived / deprecated 返回 asset_not_active，
# list_knowledge() / retrieval 默认排除三者，故运营聚合也不得统计它们。
# needs_update 是 active-like 的治理状态，仍可发现、仍统计，故不在此列。
_INACTIVE_ASSET_STATUSES = [
    AssetStatus.archived.value,
    AssetStatus.deprecated.value,
    AssetStatus.deleted.value,
]
_RECENT_JOBS = 5
_DEFAULT_DAYS = 30
_MAX_DAYS = 180
_DEFAULT_LIMIT = 10
_MAX_LIMIT = 50
_SCOPES = {"personal", "project", "company", "all"}


def _is_admin(caller: CallerContext) -> bool:
    return CompanyRole.admin.value in caller.active_company_roles


def _is_ops_viewer(caller: CallerContext) -> bool:
    """治理范围视图：业务治理角色（boss/咨询总监）或系统 admin。"""
    return _is_admin(caller) or caller.can_discover_l5


def _require_access(caller: CallerContext) -> None:
    if not caller.is_active or not (caller.is_business_user or _is_admin(caller)):
        raise denied(403, "insights_forbidden", "无权查看知识运营洞察")


def _asset_visibility_conditions(caller: CallerContext) -> list:
    """资产可见性条件；公司职务不自动形成跨项目访问权。"""
    if _is_admin(caller):
        # admin 仅消费无标题系统聚合；个人知识仍不可进入统计。
        return [
            or_(
                KnowledgeAsset.scope != KnowledgeScope.personal.value,
                KnowledgeAsset.owner_user_id == caller.user_id,
            )
        ]
    pids = list(caller.active_project_ids) or [uuid.UUID(int=0)]
    return [
        or_(
            KnowledgeAsset.owner_user_id == caller.user_id,
            KnowledgeAsset.scope == KnowledgeScope.company.value,
            KnowledgeAsset.project_id.in_(pids),
        )
    ]


def _discoverable_asset_cond():
    """资产发现层范围条件：排除 archived / deprecated / deleted。

    与 `/knowledge` 列表 / 详情 / 搜索的发现权限对齐——不可发现资产不得进入索引 / 解析 /
    原文申请 / 升格 / 生命周期等运营聚合与 drilldown。needs_update 不在排除列表，照常统计。
    """
    return KnowledgeAsset.asset_status.notin_(_INACTIVE_ASSET_STATUSES)


def _scope_conditions(scope: str, project_id: uuid.UUID | None) -> list:
    conds: list = []
    if scope and scope != "all":
        conds.append(KnowledgeAsset.scope == scope)
    if scope == KnowledgeScope.project.value and project_id is not None:
        conds.append(KnowledgeAsset.project_id == project_id)
    return conds


async def get_ops_insights(
    session: AsyncSession,
    caller: CallerContext,
    *,
    scope: str | None,
    project_id: uuid.UUID | None,
    days: int | None,
    limit: int | None,
) -> KnowledgeOpsInsightsResponse:
    """构建 `/knowledge` 运营洞察安全聚合。"""
    _require_access(caller)

    scope_v = scope if scope in _SCOPES else "all"
    window_days = max(1, min(int(days or _DEFAULT_DAYS), _MAX_DAYS))
    item_limit = max(1, min(int(limit or _DEFAULT_LIMIT), _MAX_LIMIT))
    title_visible = caller.is_business_user  # 纯 admin → False
    ops_viewer = _is_ops_viewer(caller)
    window_start = utc_now() - timedelta(days=window_days)

    vis = _asset_visibility_conditions(caller)
    scope_conds = _scope_conditions(scope_v, project_id)

    async def _count(stmt) -> int:
        return int((await session.execute(stmt)).scalar() or 0)

    # ---- Indexing：active version + 可见资产（非删除）----
    def _version_count(*extra):
        return (
            select(func.count())
            .select_from(KnowledgeAssetVersion)
            .join(KnowledgeAsset, KnowledgeAssetVersion.asset_id == KnowledgeAsset.id)
            .where(
                KnowledgeAssetVersion.version_status == _ACTIVE_VERSION,
                _discoverable_asset_cond(),
                *vis,
                *scope_conds,
                *extra,
            )
        )

    indexing = IndexingInsights(
        index_failed=await _count(
            _version_count(KnowledgeAssetVersion.index_status == "index_failed")
        ),
        skipped=await _count(_version_count(KnowledgeAssetVersion.index_status == "skipped")),
        not_indexed=await _count(
            _version_count(KnowledgeAssetVersion.index_status == "not_indexed")
        ),
        parse_failed=await _count(
            _version_count(KnowledgeAssetVersion.weknora_parse_status == "failed")
        ),
        parse_pending=await _count(
            _version_count(KnowledgeAssetVersion.weknora_parse_status == "pending")
        ),
        parse_processing=await _count(
            _version_count(KnowledgeAssetVersion.weknora_parse_status == "processing")
        ),
        kb_init_failed=await _count(_kb_init_failed_stmt(caller, scope_v, project_id)),
        recent_jobs=(await _recent_jobs(session) if ops_viewer else []),
    )

    # ---- Access：原文申请 / 授权（可见资产）----
    timeout_hours = await access_request_timeout_hours(session)
    pending = await _count(
        _request_count(vis, scope_conds, OriginalAccessRequest.status == "pending")
    )
    auto_approved = await _count(
        _request_count(
            vis,
            scope_conds,
            OriginalAccessRequest.status == "approved",
            OriginalAccessRequest.reviewer_user_id.is_(None),
            OriginalAccessRequest.reviewed_at >= window_start,
        )
    )
    if timeout_hours is not None:
        cutoff = utc_now() - timedelta(hours=timeout_hours)
        overdue = await _count(
            _request_count(
                vis,
                scope_conds,
                OriginalAccessRequest.status == "pending",
                OriginalAccessRequest.created_at < cutoff,
            )
        )
    else:
        overdue = 0
    access = AccessInsights(
        pending_original_requests=pending,
        overdue_original_requests=overdue,
        recent_auto_approved=auto_approved,
        timeout_enabled=timeout_hours is not None,
    )

    # ---- Lifecycle / Governance ----
    lifecycle = LifecycleInsights(
        archive_candidates=await _count(
            _lifecycle_event_count(
                vis, scope_conds, LifecycleEventType.archive_candidate.value, window_start
            )
        ),
        archive_warnings=await _count(
            _lifecycle_event_count(
                vis, scope_conds, LifecycleEventType.archive_warning.value, window_start
            )
        ),
        needs_update=await _count(
            select(func.count())
            .select_from(KnowledgeAsset)
            .where(
                KnowledgeAsset.asset_status == AssetStatus.needs_update.value, *vis, *scope_conds
            )
        ),
        reuse_upgrade_candidates=await _count(_upgrade_reco_count(vis, scope_conds, window_start)),
    )

    recent_items = await _recent_index_failed_items(
        session, vis, scope_conds, item_limit, title_visible=title_visible
    )
    kb_failure_cards = await _kb_init_failed_cards(session, caller, scope_v, project_id)
    cards = _build_cards(indexing, access, lifecycle, kb_failure_cards=kb_failure_cards)
    recommendations = _build_recommendations(indexing, access, lifecycle, ops_viewer=ops_viewer)

    return KnowledgeOpsInsightsResponse(
        title_visible=title_visible,
        scope=scope_v,
        window_days=window_days,
        cards=cards,
        indexing=indexing,
        access=access,
        lifecycle=lifecycle,
        recommendations=recommendations,
        recent_items=recent_items,
    )


def _kb_init_failed_stmt(caller: CallerContext, scope_v: str, project_id: uuid.UUID | None):
    """KB 初始化失败计数（按可见范围限定 mapping）。"""
    return (
        select(func.count())
        .select_from(WeknoraKbMapping)
        .where(*_kb_init_failed_conditions(caller, scope_v, project_id))
    )


def _kb_init_failed_conditions(
    caller: CallerContext, scope_v: str, project_id: uuid.UUID | None
) -> list:
    conds = [WeknoraKbMapping.status == "init_failed"]
    if not _is_admin(caller):
        pids = list(caller.active_project_ids) or [uuid.UUID(int=0)]
        conds.append(
            or_(
                WeknoraKbMapping.owner_user_id == caller.user_id,
                WeknoraKbMapping.scope == KnowledgeScope.company.value,
                WeknoraKbMapping.project_id.in_(pids),
            )
        )
    else:
        # 治理/admin：排除他人个人 KB。
        conds.append(
            or_(
                WeknoraKbMapping.scope != KnowledgeScope.personal.value,
                WeknoraKbMapping.owner_user_id == caller.user_id,
            )
        )
    if scope_v and scope_v != "all":
        conds.append(WeknoraKbMapping.scope == scope_v)
    if scope_v == KnowledgeScope.project.value and project_id is not None:
        conds.append(WeknoraKbMapping.project_id == project_id)
    return conds


async def _kb_init_failed_cards(
    session: AsyncSession,
    caller: CallerContext,
    scope_v: str,
    project_id: uuid.UUID | None,
) -> list[InsightCard]:
    rows = (
        await session.execute(
            select(
                WeknoraKbMapping.scope,
                WeknoraKbMapping.project_id,
                func.count(),
            )
            .where(*_kb_init_failed_conditions(caller, scope_v, project_id))
            .group_by(WeknoraKbMapping.scope, WeknoraKbMapping.project_id)
        )
    ).all()
    project_ids = {pid for scope_, pid, _count in rows if scope_ == "project" and pid}
    project_names: dict[uuid.UUID, str] = {}
    if project_ids:
        project_names = dict(
            (
                await session.execute(
                    select(Project.id, Project.name).where(Project.id.in_(project_ids))
                )
            )
            .tuples()
            .all()
        )
    labels = {
        "company": "公司知识库",
        "personal": "个人知识库",
        "project": "项目知识库",
    }
    return [
        InsightCard(
            key="kb_init_failed",
            label="知识库初始化失败",
            count=int(count or 0),
            severity="error",
            action_hint="检查对应知识库状态与底座模型配置",
            scope=scope_,
            project_id=pid if caller.is_business_user else None,
            context_label=(
                project_names.get(pid) if pid and caller.is_business_user else labels.get(scope_)
            ),
        )
        for scope_, pid, count in rows
        if int(count or 0) > 0
    ]


def _request_count(vis: list, scope_conds: list, *extra):
    # 不可发现资产（archived / deprecated / deleted）上的原文申请不计入待处理 / 超时聚合。
    return (
        select(func.count())
        .select_from(OriginalAccessRequest)
        .join(KnowledgeAsset, OriginalAccessRequest.asset_id == KnowledgeAsset.id)
        .where(_discoverable_asset_cond(), *vis, *scope_conds, *extra)
    )


def _lifecycle_event_count(vis: list, scope_conds: list, event_type: str, window_start: datetime):
    # 生命周期治理信号只反映「当前仍需处理」的候选 / 预警：资产一旦进入 archived /
    # deprecated / deleted 终态即不再下钻，避免历史事件长期污染当前运营面板。
    return (
        select(func.count(func.distinct(AssetLifecycleEvent.asset_id)))
        .select_from(AssetLifecycleEvent)
        .join(KnowledgeAsset, AssetLifecycleEvent.asset_id == KnowledgeAsset.id)
        .where(
            AssetLifecycleEvent.event_type == event_type,
            AssetLifecycleEvent.created_at >= window_start,
            _discoverable_asset_cond(),
            *vis,
            *scope_conds,
        )
    )


def _upgrade_reco_count(vis: list, scope_conds: list, window_start: datetime):
    # 升格推荐只面向可发现的项目资产；已退场资产不再推荐升格。
    return (
        select(func.count(func.distinct(AuditEvent.target_id)))
        .select_from(AuditEvent)
        .join(KnowledgeAsset, AuditEvent.target_id == KnowledgeAsset.id)
        .where(
            AuditEvent.action == AuditAction.knowledge_upgrade_recommended.value,
            AuditEvent.created_at >= window_start,
            _discoverable_asset_cond(),
            *vis,
            *scope_conds,
        )
    )


async def _recent_jobs(session: AsyncSession) -> list[InsightJobItem]:
    rows = list(
        (
            await session.execute(
                select(IndexingOperationJob)
                .order_by(IndexingOperationJob.requested_at.desc())
                .limit(_RECENT_JOBS)
            )
        )
        .scalars()
        .all()
    )
    return [
        InsightJobItem(
            job_id=j.id,
            operation_type=j.operation_type,
            status=j.status,
            total_count=j.total_count,
            success_count=j.success_count,
            failed_count=j.failed_count,
            skipped_count=j.skipped_count,
            requested_at=j.requested_at,
            finished_at=j.finished_at,
        )
        for j in rows
    ]


async def _recent_index_failed_items(
    session: AsyncSession, vis: list, scope_conds: list, limit: int, *, title_visible: bool
) -> list[InsightRecentItem]:
    """最近 index_failed 资产 drilldown（安全字段）。title 在 title_visible=false 时隐藏。"""
    rows = (
        await session.execute(
            select(
                KnowledgeAsset.id,
                KnowledgeAsset.title,
                KnowledgeAsset.scope,
                KnowledgeAssetVersion.index_status,
                KnowledgeAssetVersion.index_error_code,
                KnowledgeAsset.updated_at,
            )
            .join(KnowledgeAssetVersion, KnowledgeAssetVersion.asset_id == KnowledgeAsset.id)
            .where(
                KnowledgeAssetVersion.version_status == _ACTIVE_VERSION,
                _discoverable_asset_cond(),
                KnowledgeAssetVersion.index_status == "index_failed",
                *vis,
                *scope_conds,
            )
            .order_by(KnowledgeAsset.updated_at.desc())
            .limit(limit)
        )
    ).all()
    items: list[InsightRecentItem] = []
    for aid, title, scope_, status, err_code, updated_at in rows:
        scode = error_catalog.safe_code(err_code)
        items.append(
            InsightRecentItem(
                asset_id=aid,
                scope=scope_,
                status=status,
                title=title if title_visible else None,
                message=error_catalog.get_error(scode).user_message,
                updated_at=updated_at,
            )
        )
    return items


def _build_cards(
    indexing: IndexingInsights,
    access: AccessInsights,
    lifecycle: LifecycleInsights,
    *,
    kb_failure_cards: list[InsightCard],
) -> list[InsightCard]:
    """从真实计数构建概要卡片（仅非零信号，空则前端显示「暂无需要处理的运营项」）。"""
    specs = [
        ("index_failed", "索引失败", indexing.index_failed, "warning", "进入索引恢复控制台处理"),
        (
            "parse_failed",
            "解析失败",
            indexing.parse_failed,
            "warning",
            "可在索引运维面板发起重新解析",
        ),
        (
            "pending_original_requests",
            "原文申请待处理",
            access.pending_original_requests,
            "info",
            "前往原文访问审批",
        ),
        (
            "overdue_original_requests",
            "原文申请超时",
            access.overdue_original_requests,
            "warning",
            "尽快审批或检查自动通过规则",
        ),
        (
            "archive_candidates",
            "归档候选",
            lifecycle.archive_candidates,
            "info",
            "复核生命周期归档候选",
        ),
        (
            "reuse_upgrade_candidates",
            "升格推荐",
            lifecycle.reuse_upgrade_candidates,
            "info",
            "评估项目资产升格为公司资产",
        ),
    ]
    cards = [
        InsightCard(key=k, label=label, count=count, severity=sev, action_hint=hint)
        for (k, label, count, sev, hint) in specs
        if count > 0
    ]
    return [*cards, *kb_failure_cards]


def _build_recommendations(
    indexing: IndexingInsights,
    access: AccessInsights,
    lifecycle: LifecycleInsights,
    *,
    ops_viewer: bool,
) -> list[Recommendation]:
    recs: list[Recommendation] = []
    if indexing.index_failed > 0:
        if ops_viewer:
            recs.append(
                Recommendation(
                    key="retry_index_failed",
                    severity="warning",
                    message=f"有 {indexing.index_failed} 个资产索引失败，建议进入索引恢复控制台处理。",
                    target="/admin/ingest",
                )
            )
        else:
            recs.append(
                Recommendation(
                    key="retry_index_failed",
                    severity="warning",
                    message=f"你可见范围内有 {indexing.index_failed} 个资产索引失败，可在资产详情页恢复索引。",
                    target=None,
                )
            )
    if ops_viewer and indexing.parse_failed > 0:
        recs.append(
            Recommendation(
                key="reparse_failed",
                severity="warning",
                message=f"有 {indexing.parse_failed} 个资产底座解析异常，可在索引运维面板发起重新解析。",
                target="/admin/ingest",
            )
        )
    if access.overdue_original_requests > 0:
        recs.append(
            Recommendation(
                key="review_overdue_requests",
                severity="warning",
                message=f"有 {access.overdue_original_requests} 条原文访问申请已超时待处理，建议尽快审批。",
                target="/original-access",
            )
        )
    if ops_viewer and lifecycle.reuse_upgrade_candidates > 0:
        recs.append(
            Recommendation(
                key="review_upgrade_candidates",
                severity="info",
                message=f"有 {lifecycle.reuse_upgrade_candidates} 个项目资产被跨项目复用，建议评估升格。",
                target="/review",
            )
        )
    return recs

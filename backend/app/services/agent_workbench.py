"""WorkBuddy 只读工作台聚合服务（provider 中立，agent-gateway 专用）。

把员工日常工作台问题（待办 / 最近可见知识 / 知识安全摘要 / 项目资料 / 项目概览 /
待审核 / 原文申请）聚合为安全只读视图。**全部复用既有权限受控读服务**
（knowledge / review / original_access / ingest），再投影为白名单 schema。

强约束：
- **绝不重写权限矩阵**：discovery / summary / original 决策一律走
  `app.services.permission.decide()`（经 knowledge 服务），在其之上叠加注册行 token
  天花板（`external_agent_gateway.asset_within_ceiling`）——只会进一步收紧，绝不放大。
- caller 来自 token 绑定（由 API 层 `require_bound_caller` 解析），本服务不接收任何
  客户端自报身份。
- 响应只含安全治理元数据：绝不含原文 / 文件名 / 对象存储引用 / 下载·预览 URL /
  WeKnora kb·doc·chunk id / provider 内部标识 / token / token_hash / api_key /
  客户敏感数据。无权看的标题返回安全占位，不泄露存在性。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.utils import utc_now
from app.models.identity import Project
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.schemas.agent_workbench import (
    AgentWorkbenchTodoItem,
    WorkbenchKnowledgeCard,
    WorkbenchKnowledgeContent,
    WorkbenchKnowledgeListResponse,
    WorkbenchKnowledgePageResponse,
    WorkbenchKnowledgeSummary,
    WorkbenchOriginalAccessItem,
    WorkbenchOriginalAccessResponse,
    WorkbenchProjectBrief,
    WorkbenchReviewItem,
    WorkbenchReviewsResponse,
    WorkbenchTagItem,
    WorkbenchTagsResponse,
    WorkbenchTodoCounts,
    WorkbenchTodosResponse,
)
from app.schemas.enums import (
    AssetStatus,
    AuditAction,
    AuditLogType,
    KnowledgeScope,
    ReviewTaskStatus,
)
from app.schemas.permission import AccessChannel, AccessLayer, CallerContext, DeniedReason
from app.services import audit as audit_service
from app.services import discoverable_projects
from app.services import external_agent_gateway as gateway
from app.services import ingest as ingest_service
from app.services import knowledge as knowledge_service
from app.services import original_access as original_access_service
from app.services import review as review_service
from app.services.permission import decide
from app.services.permission_rules import load_access_policy
from app.services.source_content import extract_current_version_text
from app.services.storage import LocalFileStorage

# 发现层不可见的资产终态（与 /knowledge 列表 / 检索一致）。
_INACTIVE_STATUSES = (
    "processing",
    AssetStatus.archived.value,
    AssetStatus.deprecated.value,
    AssetStatus.deleted.value,
)
_NON_TERMINAL_REVIEW = (
    ReviewTaskStatus.pending_evidence.value,
    ReviewTaskStatus.pending_reviewer.value,
    ReviewTaskStatus.approving.value,
    ReviewTaskStatus.approval_failed.value,
)
_RESTRICTED_TITLE = "（受限知识）"
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_RECENT_WINDOW_DAYS = 30


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"denied_reason": reason, "message": message}
    )


def _clamp(value: int | None, *, default: int, lo: int, hi: int) -> int:
    if value is None:
        return default
    return max(lo, min(int(value), hi))


def _aware(dt: datetime | None) -> datetime:
    """把可能 naive 的时间归一为 aware UTC；None → epoch（用于稳定排序）。"""
    if dt is None:
        return _EPOCH
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 通用辅助
# ---------------------------------------------------------------------------
async def _project_name_map(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = (
        await session.execute(select(Project.id, Project.name).where(Project.id.in_(ids)))
    ).all()
    return {r[0]: r[1] for r in rows}


async def _asset_conf_map(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """资产 → confidentiality_level（用于工作台 token 天花板标题收口）。"""
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(KnowledgeAsset.id, KnowledgeAsset.confidentiality_level).where(
                KnowledgeAsset.id.in_(ids)
            )
        )
    ).all()
    return {r[0]: r[1] for r in rows}


def _ceiling_title(title: str | None, conf_level: str | None, rule) -> str | None:
    """资产标题按 token 保密天花板收口：超过天花板 → 安全占位（不泄露真实标题）。"""
    if title is None:
        return None
    if gateway.is_self_service_workbuddy_rule(rule):
        return title
    if gateway.conf_rank(conf_level) > gateway.conf_rank(rule.max_confidentiality_level):
        return _RESTRICTED_TITLE
    return title


def _active_asset_stmt():
    return (
        select(KnowledgeAsset)
        .options(selectinload(KnowledgeAsset.tags), selectinload(KnowledgeAsset.summaries))
        .where(KnowledgeAsset.asset_status.notin_(_INACTIVE_STATUSES))
    )


def _to_card(
    caller: CallerContext,
    asset: KnowledgeAsset,
    *,
    has_grant: bool,
    project_names: dict[uuid.UUID, str],
    policy,
) -> WorkbenchKnowledgeCard:
    # 复用 knowledge 服务的三层 access_info（decide 收口）与安全摘要选择，保持口径单一来源。
    access = knowledge_service._build_access_info(caller, asset, has_grant=has_grant, policy=policy)
    smap = knowledge_service._summary_map(asset)
    one_liner = (
        knowledge_service._select_summary_text(asset.confidentiality_level, smap)
        if access.summary
        else None
    )
    return WorkbenchKnowledgeCard(
        asset_id=asset.id,
        title=asset.title,
        scope=asset.scope,
        zone=asset.zone,
        asset_type=asset.asset_type,
        confidentiality_level=asset.confidentiality_level,
        one_liner=one_liner,
        updated_at=asset.updated_at,
        project_id=asset.project_id,
        project_name=project_names.get(asset.project_id) if asset.project_id else None,
        can_view_original=access.original,
    )


async def _visible_cards(
    session: AsyncSession,
    caller: CallerContext,
    rule,
    assets: list[KnowledgeAsset],
    policy,
) -> list[WorkbenchKnowledgeCard]:
    """发现层放行 + token 天花板内的资产 → 安全卡片（按 updated_at 倒序）。"""
    visible = [
        a
        for a in assets
        if decide(caller, a, AccessLayer.discovery, policy=policy).allowed
        and gateway.asset_within_ceiling(rule, a)
    ]
    granted = await original_access_service.active_grant_asset_ids(
        session, caller, [a.id for a in visible]
    )
    project_names = await _project_name_map(
        session, {a.project_id for a in visible if a.project_id}
    )
    cards = [
        _to_card(
            caller,
            a,
            has_grant=a.id in granted,
            project_names=project_names,
            policy=policy,
        )
        for a in visible
    ]
    cards.sort(key=lambda c: _aware(c.updated_at), reverse=True)
    return cards


async def _audit_agent_read(
    session: AsyncSession,
    caller: CallerContext,
    *,
    action: AuditAction,
    target_type: str,
    target_id: uuid.UUID | None = None,
    trace_id: str | None = None,
    extra: dict,
) -> None:
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=action.value,
        trace_id=trace_id or uuid.uuid4().hex,
        target_type=target_type,
        target_id=target_id,
        extra={"channel": AccessChannel.agent.value, **extra},
    )
    await session.commit()


async def _load_discoverable_project(
    session: AsyncSession, caller: CallerContext, rule, project_id: uuid.UUID
) -> tuple[Project, discoverable_projects.DiscoverableProject]:
    """Load an evidence-backed project or return the common safe 404."""
    # 无权与不存在共用同一 404 实例，保证错误形态完全一致、不泄露存在性。
    # denied_reason 统一为 project_not_found（不暴露「成员/治理」等区别原因）。
    not_available = _denied(404, "project_not_found", "项目不存在或不可用")
    discovered = await discoverable_projects.get_discoverable_project(
        session,
        caller,
        project_id,
        allowed_scope=rule.allowed_scope,
        allowed_project_id=rule.allowed_project_id,
        asset_filter=gateway.asset_ceiling_filter(rule),
    )
    if discovered is None:
        raise not_available
    project = await session.get(Project, project_id)
    if project is None:
        raise not_available
    return project, discovered


# ---------------------------------------------------------------------------
# 1) todos
# ---------------------------------------------------------------------------
async def list_todos(
    session: AsyncSession, caller: CallerContext, rule, *, limit: int | None = None
) -> WorkbenchTodosResponse:
    lim = _clamp(limit, default=50, lo=1, hi=100)
    items: list[AgentWorkbenchTodoItem] = []

    # 待我审核（reviewer 为本人且非终态）。
    reviews = await review_service.list_reviews(session, caller)
    my_reviews = [
        r
        for r in reviews
        if r.reviewer_user_id == caller.user_id and r.status in _NON_TERMINAL_REVIEW
    ]
    # 我的原文申请（pending）。
    mine = await original_access_service.list_requests(
        session, caller, box="mine", status="pending"
    )
    # 待我审批的原文申请（inbox：仅可审批的 pending）。
    inbox = await original_access_service.list_requests(session, caller, box="inbox")
    # 待确认入库任务（与 confirm 归属一致；仅安全元数据，绝不含文件名 / 抽取全文）。
    pending_ingest = await ingest_service.list_pending(session, caller)

    conf = await _asset_conf_map(
        session,
        {r.target_asset_id for r in my_reviews if r.target_asset_id is not None}
        | {it.asset_id for it in mine.items}
        | {it.asset_id for it in inbox.items},
    )

    for r in my_reviews:
        items.append(
            AgentWorkbenchTodoItem(
                todo_id=f"review:{r.id}",
                type="review",
                title="待审核知识资产",
                status=r.status,
                project_id=r.target_project_id,
                project_name=r.project_name,
                asset_id=r.target_asset_id,
                asset_title=_ceiling_title(
                    r.asset_title,
                    conf.get(r.target_asset_id) if r.target_asset_id is not None else None,
                    rule,
                ),
                created_at=r.created_at,
            )
        )
    for it in mine.items:
        items.append(
            AgentWorkbenchTodoItem(
                todo_id=f"original_access_mine:{it.request_id}",
                type="original_access_mine",
                title="我的原文访问申请",
                status=it.status,
                project_id=it.project_id,
                asset_id=it.asset_id,
                asset_title=_ceiling_title(it.asset_title, conf.get(it.asset_id), rule),
                created_at=it.created_at,
            )
        )
    for it in inbox.items:
        items.append(
            AgentWorkbenchTodoItem(
                todo_id=f"original_access_inbox:{it.request_id}",
                type="original_access_inbox",
                title="待我审批的原文访问申请",
                status=it.status,
                project_id=it.project_id,
                asset_id=it.asset_id,
                asset_title=_ceiling_title(it.asset_title, conf.get(it.asset_id), rule),
                created_at=it.created_at,
            )
        )
    for t in pending_ingest:
        items.append(
            AgentWorkbenchTodoItem(
                todo_id=f"ingest:{t.id}",
                type="ingest",
                title="待确认入库任务",
                status=t.status,
                project_id=t.target_project_id,
                asset_id=None,  # 尚未生成资产
                asset_title=None,  # 不外泄文件名 / 抽取标题
                created_at=t.created_at,
            )
        )

    # 回填项目名（无名称的项目 id 一次性映射）。
    name_map = await _project_name_map(
        session, {i.project_id for i in items if i.project_id and i.project_name is None}
    )
    for i in items:
        if i.project_id is not None and i.project_name is None:
            i.project_name = name_map.get(i.project_id)

    items.sort(key=lambda x: _aware(x.created_at), reverse=True)
    counts = WorkbenchTodoCounts(
        reviews=len(my_reviews),
        ingest=len(pending_ingest),
        original_access_mine=len(mine.items),
        original_access_inbox=len(inbox.items),
    )
    return WorkbenchTodosResponse(items=items[:lim], counts=counts)


# ---------------------------------------------------------------------------
# 2) recent knowledge
# ---------------------------------------------------------------------------
async def list_recent_knowledge(
    session: AsyncSession,
    caller: CallerContext,
    rule,
    *,
    scope: str | None = None,
    project_id: uuid.UUID | None = None,
    limit: int | None = None,
) -> WorkbenchKnowledgeListResponse:
    lim = _clamp(limit, default=10, lo=1, hi=20)
    stmt = _active_asset_stmt()
    if scope:
        stmt = stmt.where(KnowledgeAsset.scope == scope)
    if project_id is not None:
        stmt = stmt.where(KnowledgeAsset.project_id == project_id)
    assets = list((await session.execute(stmt)).scalars().all())
    policy = await load_access_policy(session)
    cards = await _visible_cards(session, caller, rule, assets, policy)
    return WorkbenchKnowledgeListResponse(items=cards[:lim], total=len(cards))


async def list_accessible_knowledge(
    session: AsyncSession,
    caller: CallerContext,
    rule,
    *,
    scope: str | None = None,
    tags: list[str] | None = None,
    asset_status: str | None = None,
    updated_from: datetime | None = None,
    updated_to: datetime | None = None,
    offset: int = 0,
    limit: int = 20,
    personal_only: bool = False,
    trace_id: str | None = None,
) -> WorkbenchKnowledgePageResponse:
    """按绑定用户实时 discovery 权限列出知识，分页前先做权限裁剪。"""
    if scope not in (None, "all", "personal", "project", "company"):
        raise _denied(422, "knowledge_scope_invalid", "知识范围参数无效")
    safe_offset = max(0, int(offset))
    safe_limit = _clamp(limit, default=20, lo=1, hi=100)
    stmt = _active_asset_stmt()
    effective_scope = "personal" if personal_only else scope
    if effective_scope not in (None, "all"):
        stmt = stmt.where(KnowledgeAsset.scope == effective_scope)
    if personal_only:
        stmt = stmt.where(KnowledgeAsset.owner_user_id == caller.user_id)
    if asset_status:
        stmt = stmt.where(KnowledgeAsset.asset_status == asset_status)
    if updated_from:
        stmt = stmt.where(KnowledgeAsset.updated_at >= updated_from)
    if updated_to:
        stmt = stmt.where(KnowledgeAsset.updated_at <= updated_to)
    assets = list((await session.execute(stmt)).scalars().all())
    if tags:
        wanted = {tag.strip() for tag in tags if tag.strip()}
        assets = [a for a in assets if wanted.issubset({t.tag_name for t in a.tags})]
    policy = await load_access_policy(session)
    cards = await _visible_cards(session, caller, rule, assets, policy)
    page = cards[safe_offset : safe_offset + safe_limit]
    await _audit_agent_read(
        session,
        caller,
        action=AuditAction.agent_knowledge_listed,
        target_type="knowledge_collection",
        trace_id=trace_id,
        extra={
            "scope": effective_scope or "all",
            "result_count": len(page),
            "access_layer": AccessLayer.discovery.value,
        },
    )
    return WorkbenchKnowledgePageResponse(
        items=page,
        total=len(cards),
        offset=safe_offset,
        limit=safe_limit,
        has_more=safe_offset + len(page) < len(cards),
    )


async def list_visible_tags(
    session: AsyncSession,
    caller: CallerContext,
    rule,
    *,
    scope: str | None = None,
    trace_id: str | None = None,
) -> WorkbenchTagsResponse:
    if scope not in (None, "all", "personal", "project", "company"):
        raise _denied(422, "knowledge_scope_invalid", "知识范围参数无效")
    stmt = _active_asset_stmt()
    if scope not in (None, "all"):
        stmt = stmt.where(KnowledgeAsset.scope == scope)
    assets = list((await session.execute(stmt)).scalars().all())
    policy = await load_access_policy(session)
    visible = [
        asset
        for asset in assets
        if decide(caller, asset, AccessLayer.discovery, policy=policy).allowed
        and gateway.asset_within_ceiling(rule, asset)
    ]
    counts: dict[str, int] = {}
    for asset in visible:
        for tag in asset.tags:
            counts[tag.tag_name] = counts.get(tag.tag_name, 0) + 1
    items = [WorkbenchTagItem(name=name, count=count) for name, count in sorted(counts.items())]
    await _audit_agent_read(
        session,
        caller,
        action=AuditAction.agent_knowledge_tags_listed,
        target_type="knowledge_tags",
        trace_id=trace_id,
        extra={
            "scope": scope or "all",
            "result_count": len(items),
            "access_layer": AccessLayer.discovery.value,
        },
    )
    return WorkbenchTagsResponse(items=items, total=len(items))


# ---------------------------------------------------------------------------
# 3) knowledge summary
# ---------------------------------------------------------------------------
async def get_knowledge_summary(
    session: AsyncSession,
    caller: CallerContext,
    rule,
    asset_id: uuid.UUID,
    *,
    trace_id: str | None = None,
) -> WorkbenchKnowledgeSummary:
    # 复用 knowledge.get_detail：不可发现 → 404（不泄露存在性）；summary 仅在放行时构建。
    detail = await knowledge_service.get_detail(session, caller, asset_id)
    # token 天花板（KnowledgeDetailOut 暴露 confidentiality_level / ai_access_level，可直接判断）。
    if not gateway.asset_within_ceiling(rule, detail):
        raise _denied(404, "knowledge_asset_not_found", "知识资产不存在或不可见")

    access = detail.access_info
    if access.original:
        access_layer = AccessLayer.original.value
    elif access.summary:
        access_layer = AccessLayer.summary.value
    else:
        access_layer = AccessLayer.discovery.value

    summary_text: str | None = None
    key_points: list[str] = []
    if detail.summary is not None:
        summary_text = detail.summary.detailed or detail.summary.one_liner
        key_points = list(detail.summary.key_points)

    available_layers = [AccessLayer.discovery.value]
    if access.summary:
        available_layers.append(AccessLayer.summary.value)
    if access.original:
        available_layers.append(AccessLayer.original.value)
    result = WorkbenchKnowledgeSummary(
        asset_id=detail.id,
        title=detail.title,
        scope=detail.scope,
        zone=detail.zone,
        asset_type=detail.asset_type,
        confidentiality_level=detail.confidentiality_level,
        summary=summary_text,
        key_points=key_points,
        tags=list(detail.tags),
        project_id=detail.project_id,
        project_name=detail.project_name,
        access_layer=access_layer,
        available_access_layers=available_layers,
        # 即便 can_view_original=True 也绝不经 MCP 返回原文（见 API 层 / schema 注释）。
        can_view_original=access.original,
        existing_original_request_status=access.existing_request_status,
    )
    await _audit_agent_read(
        session,
        caller,
        action=AuditAction.agent_knowledge_detail_viewed,
        target_type="knowledge_asset",
        target_id=asset_id,
        trace_id=trace_id,
        extra={"result_count": 1, "access_layer": access_layer},
    )
    return result


async def get_knowledge_content(
    session: AsyncSession,
    caller: CallerContext,
    rule,
    asset_id: uuid.UUID,
    *,
    storage: LocalFileStorage,
    offset: int = 0,
    max_chars: int = 4000,
    trace_id: str | None = None,
) -> WorkbenchKnowledgeContent:
    """实时 original 鉴权后返回当前版本文本页；永不读取或返回 file/storage 引用。"""
    asset = (
        await session.execute(select(KnowledgeAsset).where(KnowledgeAsset.id == asset_id))
    ).scalar_one_or_none()
    not_found = _denied(404, "knowledge_asset_not_found", "知识资产不存在或不可见")
    if asset is None:
        raise not_found
    policy = await load_access_policy(session)
    if not decide(caller, asset, AccessLayer.discovery, policy=policy).allowed:
        raise not_found
    if not gateway.asset_within_ceiling(rule, asset):
        raise not_found
    has_grant = await original_access_service.has_active_grant(session, caller.user_id, asset_id)
    channel = (
        AccessChannel.human if gateway.is_self_service_workbuddy_rule(rule) else AccessChannel.agent
    )
    original = decide(
        caller,
        asset,
        AccessLayer.original,
        channel=channel,
        policy=policy,
        has_original_grant=has_grant,
    )
    if not original.allowed:
        if original.denied_reason == DeniedReason.original_requires_request:
            raise _denied(403, original.denied_reason.value, "原文需申请并经审批后访问")
        raise _denied(403, "knowledge_original_denied", "无权读取该知识原文")

    version = (
        await session.execute(
            select(KnowledgeAssetVersion).where(
                KnowledgeAssetVersion.id == asset.current_version_id,
                KnowledgeAssetVersion.asset_id == asset.id,
                KnowledgeAssetVersion.version_status == "active",
            )
        )
    ).scalar_one_or_none()
    source = await extract_current_version_text(
        session,
        storage,
        asset_id=asset.id,
        version=version,
    )
    text = source.text
    safe_offset = max(0, int(offset))
    safe_max = _clamp(max_chars, default=4000, lo=1, hi=8000)
    content = text[safe_offset : safe_offset + safe_max]
    next_offset = safe_offset + len(content)
    has_more = next_offset < len(text)
    await _audit_agent_read(
        session,
        caller,
        action=AuditAction.agent_knowledge_content_viewed,
        target_type="knowledge_asset",
        target_id=asset_id,
        trace_id=trace_id,
        extra={
            "result_count": 1 if content else 0,
            "returned_chars": len(content),
            "content_status": source.status,
            "access_layer": AccessLayer.original.value,
        },
    )
    return WorkbenchKnowledgeContent(
        asset_id=asset_id,
        content=content,
        content_available=source.available,
        content_status=source.status,
        message=source.message,
        offset=safe_offset,
        returned_chars=len(content),
        next_offset=next_offset if has_more else None,
        has_more=has_more,
    )


# ---------------------------------------------------------------------------
# 4) project knowledge
# ---------------------------------------------------------------------------
async def list_project_knowledge(
    session: AsyncSession,
    caller: CallerContext,
    rule,
    project_id: uuid.UUID,
    *,
    limit: int | None = None,
    phase: str | None = None,
    tags: list[str] | None = None,
) -> WorkbenchKnowledgeListResponse:
    await _load_discoverable_project(session, caller, rule, project_id)
    lim = _clamp(limit, default=30, lo=1, hi=30)

    stmt = _active_asset_stmt().where(
        KnowledgeAsset.scope == KnowledgeScope.project.value,
        KnowledgeAsset.project_id == project_id,
    )
    if phase:
        stmt = stmt.where(KnowledgeAsset.lifecycle_phase_key == phase)
    assets = list((await session.execute(stmt)).scalars().all())
    if tags:
        wanted = set(tags)
        assets = [a for a in assets if wanted.intersection({t.tag_name for t in a.tags})]

    policy = await load_access_policy(session)
    cards = await _visible_cards(session, caller, rule, assets, policy)
    return WorkbenchKnowledgeListResponse(items=cards[:lim], total=len(cards))


# ---------------------------------------------------------------------------
# 5) project brief
# ---------------------------------------------------------------------------
async def get_project_brief(
    session: AsyncSession, caller: CallerContext, rule, project_id: uuid.UUID
) -> WorkbenchProjectBrief:
    project, discovered = await _load_discoverable_project(session, caller, rule, project_id)

    if discovered.access_mode == discoverable_projects.SUMMARY_VISIBLE:
        return WorkbenchProjectBrief(
            project_id=project.id,
            name=project.name,
            status=project.status,
            access_mode=discovered.access_mode,
            access_label=discovered.access_label,
            message="该项目仅摘要可见",
        )

    stmt = _active_asset_stmt().where(
        KnowledgeAsset.scope == KnowledgeScope.project.value,
        KnowledgeAsset.project_id == project_id,
    )
    assets = list((await session.execute(stmt)).scalars().all())
    policy = await load_access_policy(session)
    cards = await _visible_cards(session, caller, rule, assets, policy)
    cutoff = utc_now() - timedelta(days=_RECENT_WINDOW_DAYS)
    recent_count = sum(1 for c in cards if _aware(c.updated_at) >= cutoff)

    reviews = await review_service.list_reviews(session, caller)
    pending_reviews = sum(
        1 for r in reviews if r.target_project_id == project_id and r.status in _NON_TERMINAL_REVIEW
    )
    inbox = await original_access_service.list_requests(session, caller, box="inbox")
    pending_oar = sum(1 for it in inbox.items if it.project_id == project_id)

    return WorkbenchProjectBrief(
        project_id=project.id,
        name=project.name,
        status=project.status,
        access_mode=discovered.access_mode,
        access_label=discovered.access_label,
        phase=project.lifecycle_phase_key,
        my_role=caller.active_project_roles.get(project_id),
        knowledge_count=len(cards),
        recent_asset_count=recent_count,
        pending_review_count=pending_reviews,
        pending_original_request_count=pending_oar,
    )


# ---------------------------------------------------------------------------
# 6) pending reviews
# ---------------------------------------------------------------------------
def _due_hint(status: str) -> str:
    if status == ReviewTaskStatus.pending_evidence.value:
        return "待补充验证证据"
    if status == ReviewTaskStatus.pending_reviewer.value:
        return "待审核人处理"
    return "进行中"


async def list_pending_reviews(
    session: AsyncSession, caller: CallerContext, rule, *, limit: int | None = None
) -> WorkbenchReviewsResponse:
    lim = _clamp(limit, default=20, lo=1, hi=20)
    reviews = await review_service.list_reviews(session, caller)
    pending = [r for r in reviews if r.status in _NON_TERMINAL_REVIEW]
    pending.sort(key=lambda r: _aware(r.created_at), reverse=True)
    conf = await _asset_conf_map(
        session, {r.target_asset_id for r in pending if r.target_asset_id is not None}
    )
    items = [
        WorkbenchReviewItem(
            review_id=r.id,
            review_type=r.review_type,
            status=r.status,
            asset_id=r.target_asset_id,
            asset_title=_ceiling_title(
                r.asset_title,
                conf.get(r.target_asset_id) if r.target_asset_id is not None else None,
                rule,
            ),
            project_id=r.target_project_id,
            project_name=r.project_name,
            created_at=r.created_at,
            due_hint=_due_hint(r.status),
        )
        for r in pending[:lim]
    ]
    return WorkbenchReviewsResponse(items=items, total=len(pending))


# ---------------------------------------------------------------------------
# 7) original-access requests
# ---------------------------------------------------------------------------
async def list_original_access_requests(
    session: AsyncSession,
    caller: CallerContext,
    rule,
    *,
    box: str = "mine",
    limit: int | None = None,
) -> WorkbenchOriginalAccessResponse:
    safe_box = box if box in ("mine", "inbox") else "mine"
    lim = _clamp(limit, default=20, lo=1, hi=20)
    data = await original_access_service.list_requests(session, caller, box=safe_box)
    conf = await _asset_conf_map(session, {it.asset_id for it in data.items})
    items = [
        WorkbenchOriginalAccessItem(
            request_id=it.request_id,
            box=safe_box,
            status=it.status,
            asset_id=it.asset_id,
            asset_title=_ceiling_title(it.asset_title, conf.get(it.asset_id), rule),
            requester_name=it.requester_name,
            reviewer_name=it.reviewer_name,
            reason=it.reason,
            created_at=it.created_at,
            reviewed_at=it.reviewed_at,
            expires_at=None,  # 授权过期时间不在申请视图；不经 MCP 暴露 grant 细节
        )
        for it in data.items[:lim]
    ]
    return WorkbenchOriginalAccessResponse(items=items, total=len(data.items))

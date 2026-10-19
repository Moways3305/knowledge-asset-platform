"""统一检索 / 问答编排—— `POST /knowledge/search` 的业务层。

把意图识别 + 阶段1卡片 + 阶段2脱敏原文 + 问答自拼答案串起来，全部复用
`app.services.retrieval`（KB 路由、映射、`decide()` 复核、脱敏）与集中权限服务。
本层不重写权限矩阵，不直接发 WeKnora / LLM HTTP（经注入的 client）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetTag, KnowledgeAssetVersion
from app.schemas.enums import AuditAction, AuditLogType
from app.schemas.permission import AccessChannel, CallerContext
from app.schemas.search import (
    OriginalChunkOut,
    OriginalOut,
    SearchCardOut,
    SearchCitationOut,
    SearchRequest,
    SearchResponse,
)
from app.services import audit as audit_service
from app.services import directories, knowledge_qa, retrieval, search_queries, search_rerank
from app.services.desensitization import LlmOutputDesensitizer
from app.services.intent import classify_intent, wants_answer
from app.services.knowledge_evidence_state import attach_platform_state
from app.services.llm_client import LLMClient, NullLLMClient
from app.services.weknora_client import NullWeKnoraClient, WeKnoraClient

_logger = logging.getLogger(__name__)


@dataclass
class _SearchProgress:
    stage: str = "prepare"
    cards: list[SearchCardOut] = field(default_factory=list)
    entered_at: float = field(default_factory=time.monotonic)

    def enter(self, stage: str, trace_id: str | None) -> None:
        now = time.monotonic()
        _logger.info(
            "knowledge_qa_stage",
            extra={
                "stage": stage,
                "previous_stage": self.stage,
                "previous_duration_ms": int((now - self.entered_at) * 1000),
                "trace_id": trace_id,
            },
        )
        self.stage = stage
        self.entered_at = now


def _qa_timeout_seconds(remote_limit: float) -> float:
    return min(30.0, remote_limit * 0.8)


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"denied_reason": reason, "message": message}
    )


def _passes_filters(asset, filters) -> bool:
    """阶段1卡片级过滤：zone / tags / phase。archived 始终在召回阶段已排除。"""
    if filters.zone and asset.zone != filters.zone:
        return False
    if filters.phase and asset.lifecycle_phase_key != filters.phase:
        return False
    if filters.project_id and asset.project_id != filters.project_id:
        return False
    if filters.tags:
        asset_tags = {t.tag_name for t in asset.tags}
        if not set(filters.tags).issubset(asset_tags):
            return False
    return True


async def run_search(
    session: AsyncSession,
    caller: CallerContext,
    req: SearchRequest,
    *,
    weknora: WeKnoraClient | NullWeKnoraClient,
    llm: LLMClient | NullLLMClient,
    trace_id: str | None,
    channel: AccessChannel = AccessChannel.human,
    asset_guard: Callable[[Any], bool] | None = None,
    allow_cross_project: bool = False,
) -> SearchResponse:
    """One end-to-end QA deadline, leaving time for rollback/audit and MCP encoding."""
    intent = classify_intent((req.query or "").strip(), explicit=req.intent)
    progress = _SearchProgress()
    operation = _run_search(
        session,
        caller,
        req,
        weknora=weknora,
        llm=llm,
        trace_id=trace_id,
        channel=channel,
        asset_guard=asset_guard,
        allow_cross_project=allow_cross_project,
        progress=progress,
    )
    if not wants_answer(intent):
        return await operation
    remote_limit = max(1.0, get_settings().workbuddy_remote_timeout_seconds)
    budget = _qa_timeout_seconds(remote_limit)
    started = time.monotonic()
    try:
        return await asyncio.wait_for(operation, timeout=budget)
    except asyncio.TimeoutError:
        _logger.warning(
            "knowledge_qa_deadline",
            extra={
                "stage": progress.stage,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "trace_id": trace_id,
            },
        )
        # Cancellation can interrupt a DB read or the audit transaction. Never
        # reuse that transaction or relay a partially generated answer.
        cleanup_budget = min(2.0, remote_limit * 0.05)
        await asyncio.wait_for(session.rollback(), timeout=cleanup_budget)
        await asyncio.wait_for(
            _record_deadline(session, caller, req, intent.value, channel, progress, trace_id),
            timeout=cleanup_budget,
        )
        return SearchResponse(
            intent=intent.value,
            cards=progress.cards,
            answer_status="unavailable",
            answer_message="知识问答处理超时，暂未生成可验证答案。请稍后重试；若持续出现，请联系管理员排查。",
            trace_id=trace_id,
        )


async def _record_deadline(session, caller, req, intent, channel, progress, trace_id) -> None:
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.knowledge_searched.value,
        trace_id=trace_id,
        target_type="knowledge_search",
        extra={
            "intent": intent,
            "scope": req.scope or "all",
            "card_count": len(progress.cards),
            "answered": False,
            "answer_status": "unavailable",
            "channel": channel.value,
            "directory_key": req.filters.directory_key,
            "timeout_stage": progress.stage,
        },
    )
    await session.commit()


async def _run_search(
    session: AsyncSession,
    caller: CallerContext,
    req: SearchRequest,
    *,
    weknora: WeKnoraClient | NullWeKnoraClient,
    llm: LLMClient | NullLLMClient,
    trace_id: str | None,
    channel: AccessChannel,
    asset_guard: Callable[[Any], bool] | None,
    allow_cross_project: bool,
    progress: _SearchProgress,
) -> SearchResponse:
    """统一检索 / 问答主流程。

    channel 决定访问渠道：控制台/人工默认 human；外部 Agent 工具传 agent，使
    A4 原文降级等 Agent 渠道边界生效。权限矩阵仍全由 `decide()` 收口，不在此重写。
    """
    if not caller.is_active:
        raise _denied(403, "user_inactive", "用户已停用")
    query = (req.query or "").strip()
    if not query:
        raise _denied(422, "query_required", "查询不能为空")

    intent = classify_intent(query, explicit=req.intent)
    desens = LlmOutputDesensitizer(llm)

    # ---- 阶段2：want_original + asset_id → 取某资产脱敏原文 ----
    original_out: OriginalOut | None = None
    if req.want_original and req.asset_id is not None:
        progress.enter("original", trace_id)
        res = await retrieval.fetch_stage2_original(
            session,
            caller,
            weknora,
            desens,
            asset_id=req.asset_id,
            query=query,
            channel=channel,
            trace_id=trace_id,
        )
        original_out = OriginalOut(
            asset_id=res.asset.id if res.asset is not None else None,
            available=res.available,
            chunks=[OriginalChunkOut(seq=c["seq"], content=c["content"]) for c in res.chunks],
            degraded_reason=res.degraded_reason,
            owner_name=res.owner_name,
            maintainer_name=res.maintainer_name,
        )

    # ---- 阶段1：召回 + 卡片 ----
    if req.filters.project_id is not None:
        if req.scope != "project":
            raise _denied(
                422,
                "project_filter_scope_mismatch",
                "Project filtering requires project scope",
            )
        if req.filters.project_id not in caller.active_project_ids and not allow_cross_project:
            raise _denied(
                403,
                "project_membership_required",
                "Active project membership is required",
            )

    knowledge_ids: list[str] | None = None
    recalled: list[retrieval.RecalledAsset] | None = None
    if req.filters.directory_key:
        directory_scope = (
            req.scope
            if req.scope not in (None, "all")
            else req.filters.directory_key.split(".", 1)[0]
        )
        assert directory_scope is not None
        await directories.validate_directory(
            session,
            directory_key=req.filters.directory_key,
            scope=directory_scope,
            project_id=req.filters.project_id,
        )
        knowledge_ids = await directories.directory_document_ids(
            session,
            directory_key=req.filters.directory_key,
            scope=req.scope,
            project_id=req.filters.project_id,
        )
        if not knowledge_ids:
            recalled = []
        else:
            recalled = None
    kb_ids = (
        await retrieval.resolve_project_kbs(session, req.filters.project_id)
        if req.filters.project_id is not None
        else await retrieval.resolve_searchable_kbs(session, caller, req.scope)
    )
    # Apply business filters before the upstream chunk budget is consumed.
    # Keep the post-recall filters and permission checks as defence in depth.
    if req.filters.tags or req.filters.zone or req.filters.phase:
        stmt = (
            select(KnowledgeAssetVersion.weknora_doc_id)
            .join(
                KnowledgeAsset,
                and_(
                    KnowledgeAssetVersion.asset_id == KnowledgeAsset.id,
                    or_(
                        KnowledgeAsset.current_version_id == KnowledgeAssetVersion.id,
                        KnowledgeAsset.current_version_id.is_(None),
                    ),
                ),
            )
            .where(
                KnowledgeAssetVersion.asset_id == KnowledgeAsset.id,
                KnowledgeAssetVersion.weknora_kb_id.in_(kb_ids),
                KnowledgeAssetVersion.index_status == "indexed",
                KnowledgeAssetVersion.version_status == "active",
                KnowledgeAsset.asset_status == "active",
            )
        )
        for tag in req.filters.tags or []:
            stmt = stmt.where(KnowledgeAsset.tags.any(KnowledgeAssetTag.tag_name == tag))
        if req.filters.zone:
            stmt = stmt.where(KnowledgeAsset.zone == req.filters.zone)
        if req.filters.phase:
            stmt = stmt.where(KnowledgeAsset.lifecycle_phase_key == req.filters.phase)
        if knowledge_ids is not None:
            stmt = stmt.where(KnowledgeAssetVersion.weknora_doc_id.in_(knowledge_ids))
        knowledge_ids = [row[0] for row in (await session.execute(stmt)).all() if row[0]]
        if not knowledge_ids:
            recalled = []
    if recalled is None:
        progress.enter("query_planning", trace_id)
        planned = (
            await search_queries.plan_queries(llm, query, trace_id=trace_id)
            if kb_ids and knowledge_ids != []
            else [query]
        )
        progress.enter("recall", trace_id)
        recalled = await retrieval.recall_assets(
            session,
            caller,
            weknora,
            query=query,
            kb_ids=kb_ids,
            knowledge_ids=knowledge_ids,
            channel=channel,
            trace_id=trace_id,
            search_queries=planned,
        )
    recalled = [
        r
        for r in recalled
        if _passes_filters(r.asset, req.filters) and (asset_guard is None or asset_guard(r.asset))
    ]
    progress.enter("cards", trace_id)
    projects, users = await retrieval.load_card_aux(session, [r.asset for r in recalled])
    cards = []
    directory_paths: dict = {}
    for r in recalled:
        key = directories.version_directory_key(r.version)
        path = await directories.display_path(session, key, r.asset.project_id)
        directory_paths[r.asset.id] = (key, path)
        cards.append(
            SearchCardOut(
                **retrieval.build_card(r, projects, users),
                directory_key=key,
                directory_path=path,
            )
        )

    progress.cards = cards
    progress.enter("reranking", trace_id)
    cards = await search_rerank.rerank_cards(llm, query, cards, trace_id=trace_id)
    progress.cards = cards
    # Evidence follows the same permission-filtered order seen in the cards.
    # The model cannot introduce IDs or change a candidate's permissions.
    rank = {card.asset_id: index for index, card in enumerate(cards)}
    recalled.sort(key=lambda r: rank[r.asset.id])
    # ---- 问答 / 生成 / 总结 / 检查：放行证据 → 脱敏 → LLM 自拼答案 + 引用
    # D1 阶段4：子块召回 → 父文件全文给 Agent（无 chunk 存量资产自动回退片段/摘要）。
    answer: str | None = None
    answer_status: Literal["not_requested", "answered", "insufficient_evidence", "unavailable"] = (
        "not_requested"
    )
    answer_message: str | None = None
    citations: list[SearchCitationOut] = []
    if wants_answer(intent):
        progress.enter("evidence", trace_id)
        evidences = await retrieval.gather_parent_context(
            session,
            recalled,
            desens,
            trace_id=trace_id,
        )
        await attach_platform_state(
            session, caller, evidences, recalled, channel=channel, asset_guard=asset_guard
        )
        progress.enter("answer", trace_id)
        outcome = await knowledge_qa.generate_answer(llm, query, evidences, trace_id=trace_id)
        answer, answer_status, answer_message = outcome.answer, outcome.status, outcome.message
        for order, e in enumerate(evidences, start=1):
            if order not in outcome.citation_orders:
                continue
            citations.append(
                SearchCitationOut(
                    asset_id=e.asset.id,
                    asset_title=e.asset.title,
                    scope=e.asset.scope,
                    cited_zone=e.asset.zone,
                    used_access_layer=e.used_layer,
                    seq=e.seq,
                    snippet=e.snippet,
                    citation_order=order,
                    directory_key=directory_paths.get(e.asset.id, (None, None))[0],
                    directory_path=directory_paths.get(e.asset.id, (None, None))[1],
                )
            )

    # ---- 检索审计（operation；只记安全元数据，不记原始 query / kb/doc id）----
    progress.enter("audit", trace_id)
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.knowledge_searched.value,
        trace_id=trace_id,
        target_type="knowledge_search",
        extra={
            "intent": intent.value,
            "scope": req.scope or "all",
            "card_count": len(cards),
            "answered": answer_status == "answered",
            "answer_status": answer_status,
            "channel": channel.value,
            "directory_key": req.filters.directory_key,
        },
    )
    await session.commit()

    progress.enter("complete", trace_id)
    return SearchResponse(
        intent=intent.value,
        cards=cards,
        answer=answer,
        answer_status=answer_status,
        answer_message=answer_message,
        citations=citations,
        original=original_out,
        trace_id=trace_id,
    )

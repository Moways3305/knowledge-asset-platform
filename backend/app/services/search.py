"""统一检索 / 问答编排—— `POST /knowledge/search` 的业务层。

把意图识别 + 阶段1卡片 + 阶段2脱敏原文 + 问答自拼答案串起来，全部复用
`app.services.retrieval`（KB 路由、映射、`decide()` 复核、脱敏）与集中权限服务。
本层不重写权限矩阵，不直接发 WeKnora / LLM HTTP（经注入的 client）。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.services import directories, retrieval
from app.services.desensitization import LlmOutputDesensitizer
from app.services.intent import classify_intent, wants_answer
from app.services.llm_client import LLMClient, NullLLMClient
from app.services.weknora_client import NullWeKnoraClient, WeKnoraClient


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
    knowledge_ids: list[str] | None = None
    if req.filters.directory_key:
        if (
            req.filters.project_id is not None
            and req.filters.project_id not in caller.active_project_ids
        ):
            raise HTTPException(
                status_code=403,
                detail={
                    "denied_reason": "project_membership_required",
                    "message": "Active project membership is required",
                },
            )
        await directories.validate_directory(
            session,
            directory_key=req.filters.directory_key,
            scope=req.scope
            if req.scope not in (None, "all")
            else req.filters.directory_key.split(".", 1)[0],
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
    else:
        recalled = None
    kb_ids = await retrieval.resolve_searchable_kbs(session, caller, req.scope)
    if recalled is None:
        recalled = await retrieval.recall_assets(
            session,
            caller,
            weknora,
            query=query,
            kb_ids=kb_ids,
            knowledge_ids=knowledge_ids,
            channel=channel,
            trace_id=trace_id,
        )
    recalled = [
        r
        for r in recalled
        if _passes_filters(r.asset, req.filters) and (asset_guard is None or asset_guard(r.asset))
    ]
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

    # ---- 问答 / 生成 / 总结 / 检查：放行证据 → 脱敏 → LLM 自拼答案 + 引用
    # D1 阶段4：子块召回 → 父文件全文给 Agent（无 chunk 存量资产自动回退片段/摘要）。
    answer: str | None = None
    citations: list[SearchCitationOut] = []
    if wants_answer(intent):
        evidences = await retrieval.gather_parent_context(
            session,
            recalled,
            desens,
            trace_id=trace_id,
        )
        answer = await retrieval.synthesize_answer(llm, query, evidences, trace_id=trace_id)
        for order, e in enumerate(evidences, start=1):
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
            "answered": answer is not None,
            "channel": channel.value,
            "directory_key": req.filters.directory_key,
        },
    )
    await session.commit()

    return SearchResponse(
        intent=intent.value,
        cards=cards,
        answer=answer,
        citations=citations,
        original=original_out,
        trace_id=trace_id,
    )

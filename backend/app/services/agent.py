"""Agent / Dify Gateway 服务（真实检索 + 外部 LLM 自拼答案）。

跑通：项目 Q&A → 以真实调用人身份复用集中权限判断 → **WeKnora chunk 级召回**（取代
的关键词粗召回）→ 记录调用 / 决策 / 候选项 / 引用 → **放行+脱敏 chunk 喂
外部 LLM 自拼答案**（取代确定性占位答案）+ 真实片段引用。

本服务取代并删除了 internal_stub 的关键词召回与确定性占位答案，但**复用** agent_calls /
agent_gateway_decisions / decision_items / citations 权限-审计骨架与全部边界。

当前边界：
- 不接真实 Dify；不引入 Dify SDK；不保存 Dify app_id / workflow_id / dataset_id / api_key。
- 召回 / 脱敏 / 答案为同步调用（不在本服务内做 Celery 异步）。
- Agent 不拥有独立权限，完全跟随 caller：能力、范围、原文层都由
  `app.services.permission.decide(..., channel=agent)` 决定。

关键安全约束（不变）：
- A4 资产在 channel=agent 请求 original 时被强制降级（最多 summary），不进原文上下文。
- L5 对无发现权用户被 decide(discovery) 过滤，不进候选 / 引用 / 可见明细（避免存在性泄露）。
- archived / deprecated / 非 active 版本 / 孤儿 knowledge 由检索映射阶段丢弃。
- citation 必须来自放行候选，used_access_layer = 该候选可达最高层级，不越权。
- 引用片段（snippet）也必经输出脱敏（L3/L4/L5 走 LLM 擦洗）；WeKnora chunk 引用 server-only。
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import (
    AgentCall,
    AgentCallCitation,
    AgentGatewayDecision,
    AgentGatewayDecisionItem,
)
from app.models.identity import Project, User
from app.models.knowledge import KnowledgeAsset
from app.schemas.agent import (
    AgentCallDetailResponse,
    CitationOut,
    DecisionItemOut,
    DecisionItemsResponse,
    ProjectQaModelOptionOut,
    ProjectQaModelOptionsResponse,
    ProjectQaRequest,
    ProjectQaResponse,
)
from app.schemas.enums import (
    AgentCallStatus,
    AgentCapability,
    AgentProvider,
    AiAccessLevel,
    AlertSeverity,
    AuditAction,
    AuditLogType,
    AuditRiskLevel,
    GatewayDecisionStatus,
    KnowledgeScope,
    KnowledgeZone,
)
from app.schemas.permission import (
    AccessChannel,
    AccessLayer,
    CallerContext,
    DeniedReason,
)
from app.services import audit as audit_service
from app.services import generation_models, retrieval
from app.services.desensitization import LlmOutputDesensitizer
from app.services.llm_client import LLMClient, NullLLMClient
from app.services.weknora_client import NullWeKnoraClient, WeKnoraClient

# provider：平台抽象标识。已接真实 WeKnora 检索 + 外部 LLM，故 provider 为
# weknora_llm（非 internal_stub 桩）。仍是平台内部抽象，不暴露 Dify / WeKnora / LLM
# 内部敏感标识。
PROVIDER = AgentProvider.weknora_llm.value

# 对外 decision-items / 审计响应中应隐藏的"不可发现"拒绝原因：
# 这些原因若暴露 target_asset_id 会泄露 L5 / 他人个人知识的存在。
_LEAKY_DENIED_REASONS = {
    DeniedReason.l5_not_discoverable.value,
    DeniedReason.personal_asset_not_owned.value,
}


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"denied_reason": reason, "message": message}
    )


def _is_governance(caller: CallerContext) -> bool:
    """业务治理角色（boss / consulting_director）。"""
    return caller.can_discover_l5


def _can_view_call(caller: CallerContext, call: AgentCall) -> bool:
    """调用记录可见性：本人 或 boss / 咨询总监。"""
    return call.caller_user_id == caller.user_id or _is_governance(caller)


def _layer_and_source(r: retrieval.RecalledAsset) -> tuple[str, str]:
    """候选可达最高层级 + 来源（original>summary>discovery）。recall 已保证发现层放行。"""
    if r.original is not None and r.original.allowed:
        return AccessLayer.original.value, r.original.effective_access_source.value
    if r.summary is not None and r.summary.allowed:
        return AccessLayer.summary.value, r.summary.effective_access_source.value
    # recall 已保证发现层放行（见 docstring），discovery 必非 None。
    assert r.discovery is not None
    return AccessLayer.discovery.value, r.discovery.effective_access_source.value


def _top_chunk_ref(r: retrieval.RecalledAsset) -> str | None:
    """该候选命中的首个 WeKnora chunk 引用（server-only，供审计追溯，不外泄）。"""
    if not r.matched_chunks:
        return None
    c = r.matched_chunks[0]
    return f"{c.get('knowledge_id')}#{c.get('chunk_index')}"


async def list_project_qa_model_options(
    session: AsyncSession,
    caller: CallerContext,
    project_id: uuid.UUID,
    *,
    llm: LLMClient | NullLLMClient,
) -> ProjectQaModelOptionsResponse:
    """List runnable QA choices only after project membership is established."""
    if not caller.is_active:
        raise _denied(403, DeniedReason.user_inactive.value, "用户已停用")
    if not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可查看问答模型")
    if project_id not in caller.active_project_ids:
        raise _denied(403, "project_membership_required", "需为该项目的有效成员")
    items = [
        ProjectQaModelOptionOut(**item)
        for item in await generation_models.safe_project_qa_options(session, llm)
    ]
    return ProjectQaModelOptionsResponse(items=items, total=len(items))


async def run_project_qa(
    session: AsyncSession,
    caller: CallerContext,
    project_id: uuid.UUID,
    req: ProjectQaRequest,
    trace_id: str | None,
    *,
    weknora: WeKnoraClient | NullWeKnoraClient,
    llm: LLMClient | NullLLMClient,
) -> ProjectQaResponse:
    """项目 Q&A（WeKnora 召回 + 外部 LLM 自拼答案 + 真实片段引用）。"""
    # ---- 1. 身份与边界校验（Agent 完全跟随 caller）----
    if not caller.is_active:
        await audit_service.record_denied(
            session,
            caller=caller,
            log_type=AuditLogType.exception,
            action=AuditAction.agent_denied.value,
            trace_id=trace_id,
            target_type="project",
            target_id=project_id,
            extra={"denied_reason": DeniedReason.user_inactive.value},
            project_id=project_id,
        )
        raise _denied(403, DeniedReason.user_inactive.value, "用户已停用")
    if not caller.is_business_user:
        # 纯 admin / 非业务用户不能发起 Agent 业务问答（强审计）。
        await audit_service.record_denied(
            session,
            caller=caller,
            log_type=AuditLogType.exception,
            action=AuditAction.admin_business_denied.value,
            trace_id=trace_id,
            target_type="project",
            target_id=project_id,
            severity=AlertSeverity.warning,
            risk_level=AuditRiskLevel.high.value,
            extra={"denied_reason": "admin_business_permission_denied", "attempted": "agent.qa"},
            project_id=project_id,
        )
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可发起 Agent 问答")
    if project_id not in caller.active_project_ids:
        # 无该项目有效成员关系（含项目不存在）一律按需要项目身份处理，不泄露。
        await audit_service.record_denied(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.agent_denied.value,
            trace_id=trace_id,
            target_type="project",
            target_id=project_id,
            extra={"denied_reason": "project_membership_required"},
        )
        raise _denied(403, "project_membership_required", "需为该项目的有效成员")
    if req.capability != AgentCapability.qa:
        # 当前只实现 qa；其余能力被网关能力边界拒绝。
        await audit_service.record_denied(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.agent_denied.value,
            trace_id=trace_id,
            target_type="project",
            target_id=project_id,
            extra={"denied_reason": "agent_capability_denied", "capability": req.capability.value},
            project_id=project_id,
        )
        raise _denied(403, "agent_capability_denied", "当前仅支持 qa 能力")

    query = req.query.strip()
    if not query:
        raise _denied(422, "query_required", "问题不能为空")

    model_key = req.model_ref
    try:
        selected_llm = await generation_models.resolve_project_qa_client(session, model_key, llm)
    except generation_models.GenerationModelError as exc:
        await audit_service.record_denied(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.agent_denied.value,
            trace_id=trace_id,
            target_type="project",
            target_id=project_id,
            extra={"denied_reason": exc.code, "attempted": "agent.qa_model_select"},
            project_id=project_id,
        )
        raise _denied(exc.status_code, exc.code, exc.message)

    # ---- 2. 创建 agent_calls ----
    call = AgentCall(
        caller_user_id=caller.user_id,
        project_id=project_id,
        query_text=query,
        model_key=model_key,
        provider=PROVIDER,
        capability=req.capability.value,
        call_status=AgentCallStatus.denied.value,  # 先置 denied，成功后改 allowed
        trace_id=trace_id,
    )
    session.add(call)
    await session.flush()

    # ---- 3. WeKnora chunk 级召回（限定到本项目 KB；映射回资产、去重、逐资产 decide）----
    kb_ids = await retrieval.resolve_project_kbs(session, project_id)
    recalled = await retrieval.recall_assets(
        session,
        caller,
        weknora,
        query=query,
        kb_ids=kb_ids,
        channel=AccessChannel.agent,
        trace_id=trace_id,
    )

    # ---- 4. 写调用级决策主记录（先占位，逐项判断后回填聚合值）----
    decision = AgentGatewayDecision(
        call_id=call.id,
        caller_user_id=caller.user_id,
        decision_status=GatewayDecisionStatus.denied.value,
        trace_id=trace_id,
    )
    session.add(decision)
    await session.flush()

    # ---- 5. 逐候选写 decision_items（recall 已过滤发现层不可达者）----
    item_by_asset: dict[uuid.UUID, AgentGatewayDecisionItem] = {}
    any_discovery = any_summary = any_original = False
    primary_source: str | None = None
    a4_downgraded: list[KnowledgeAsset] = []
    for r in recalled:
        asset = r.asset
        layer, source = _layer_and_source(r)
        summary_allowed = bool(r.summary and r.summary.allowed)
        original_allowed = bool(r.original and r.original.allowed)
        # A4 资产在 agent 渠道：可发现但 original 被强制降级，记录用于强审计。
        if asset.ai_access_level == AiAccessLevel.A4.value and not original_allowed:
            a4_downgraded.append(asset)
        item = AgentGatewayDecisionItem(
            decision_id=decision.id,
            call_id=call.id,
            caller_user_id=caller.user_id,
            target_asset_id=asset.id,
            target_chunk_id=None,  # 我们不落地自有 chunk 行；WeKnora chunk 引用见下方 server-only 列
            target_weknora_chunk_ref=_top_chunk_ref(r),  # server-only，绝不外泄
            target_project_id=asset.project_id,
            target_scope=asset.scope,
            target_confidentiality_level=asset.confidentiality_level,
            target_ai_access_level=asset.ai_access_level,
            discovery_allowed=True,
            summary_allowed=summary_allowed,
            original_allowed=original_allowed,
            returned_layer=layer,
            effective_access_source=source,
            denied_reason=None,
        )
        session.add(item)
        item_by_asset[asset.id] = item
        any_discovery = True
        any_summary = any_summary or summary_allowed
        any_original = any_original or original_allowed
        if primary_source is None:
            primary_source = source
    await session.flush()

    # A4 在 agent 渠道被降级：逐条写强审计（severity + risk_level）。
    async def _emit_a4_denied() -> None:
        for asset in a4_downgraded:
            await audit_service.record_event(
                session,
                caller=caller,
                log_type=AuditLogType.exception,
                action=AuditAction.agent_a4_original_denied.value,
                trace_id=trace_id,
                target_type="knowledge_asset",
                target_id=asset.id,
                severity=AlertSeverity.warning,
                risk_level=AuditRiskLevel.high.value,
                extra={
                    "ai_access_level": asset.ai_access_level,
                    "confidentiality_level": asset.confidentiality_level,
                    "denied_reason": DeniedReason.agent_a4_original_denied.value,
                },
                project_id=project_id,
            )

    # 调用发起审计（无论放行/拒绝都先记 agent.called）。
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.agent_called.value,
        trace_id=trace_id,
        target_type="agent_call",
        target_id=call.id,
        extra={"capability": req.capability.value, "candidate_count": len(recalled)},
        project_id=project_id,
    )

    # ---- 6. 收集放行+脱敏证据（只来自 summary/original 放行候选；引用片段必经脱敏）----
    desens = LlmOutputDesensitizer(selected_llm)
    evidences = await retrieval.gather_evidence(recalled, desens, trace_id=trace_id)

    # 无任何可用证据（全部候选仅发现层 / 脱敏全失败 / 无召回）→ 调用整体拒绝，不编造引用。
    if not evidences:
        decision.discovery_allowed = any_discovery
        decision.summary_allowed = any_summary
        decision.original_allowed = any_original
        decision.decision_status = GatewayDecisionStatus.denied.value
        decision.denied_reason = "agent_scope_denied"
        call.call_status = AgentCallStatus.denied.value
        call.denied_reason = "agent_scope_denied"
        await _emit_a4_denied()
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.agent_denied.value,
            trace_id=trace_id,
            target_type="agent_call",
            target_id=call.id,
            extra={"denied_reason": "agent_scope_denied"},
            project_id=project_id,
        )
        await session.commit()
        raise _denied(
            403,
            "agent_scope_denied",
            "调用人权限范围内本项目无可用知识上下文，无法生成回答",
        )

    # ---- 7. 外部 LLM 自拼答案（只喂放行+脱敏证据）；LLM 不可用 → fail closed ----
    answer = await retrieval.synthesize_answer(selected_llm, query, evidences, trace_id=trace_id)
    if not answer:
        decision.discovery_allowed = any_discovery
        decision.summary_allowed = any_summary
        decision.original_allowed = any_original
        decision.decision_status = GatewayDecisionStatus.denied.value
        decision.denied_reason = "external_llm_unavailable"
        call.call_status = AgentCallStatus.denied.value
        call.denied_reason = "external_llm_unavailable"
        await _emit_a4_denied()
        await audit_service.record_denied(
            session,
            caller=caller,
            log_type=AuditLogType.exception,
            action=AuditAction.agent_denied.value,
            trace_id=trace_id,
            target_type="agent_call",
            target_id=call.id,
            extra={"denied_reason": "external_llm_unavailable"},
            project_id=project_id,
        )
        await session.commit()
        raise _denied(
            503,
            "external_llm_unavailable",
            "项目问答模型当前不可用，请稍后重试",
        )
    response_text = answer

    # ---- 8. 写 citations（引用只来自放行证据；used_access_layer=证据层级，不越权）----
    citations_out: list[CitationOut] = []
    for order, e in enumerate(evidences, start=1):
        asset = e.asset
        cited_item = item_by_asset.get(asset.id)
        session.add(
            AgentCallCitation(
                call_id=call.id,
                decision_item_id=cited_item.id if cited_item is not None else None,
                cited_asset_id=asset.id,
                cited_chunk_id=None,
                cited_weknora_chunk_ref=e.weknora_chunk_ref,  # server-only，绝不外泄
                cited_snippet=e.snippet,  # 已脱敏，可对外
                cited_seq=e.seq,
                used_access_layer=e.used_layer,
                cited_zone=asset.zone,
                citation_order=order,
            )
        )
        citations_out.append(
            CitationOut(
                asset_id=asset.id,
                asset_title=asset.title,
                scope=asset.scope,
                cited_zone=asset.zone,
                used_access_layer=e.used_layer,
                # WeKnora 不回传我们的 chunk_review 状态，当前保持 False。
                is_pending_review=False,
                is_asset_zone=asset.zone == KnowledgeZone.asset.value,
                citation_order=order,
                seq=e.seq,
                snippet=e.snippet,
            )
        )

    # ---- 9. 回填聚合结果 ----
    decision.discovery_allowed = any_discovery
    decision.summary_allowed = any_summary
    decision.original_allowed = any_original
    decision.decision_status = GatewayDecisionStatus.allowed.value
    decision.allowed_scope = KnowledgeScope.project.value
    decision.effective_access_source = primary_source
    call.response_text = response_text
    call.call_status = AgentCallStatus.allowed.value

    # 调用整体放行审计（A4 降级若有也在此前一并记录）。
    await _emit_a4_denied()
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.agent_allowed.value,
        trace_id=trace_id,
        target_type="agent_call",
        target_id=call.id,
        extra={
            "citation_count": len(citations_out),
            "effective_access_source": primary_source,
        },
        project_id=project_id,
    )
    await session.commit()

    return ProjectQaResponse(
        call_id=call.id,
        response_text=response_text,
        model_key=model_key,
        decision_status=decision.decision_status,
        citations=citations_out,
        trace_id=trace_id,
        created_at=call.created_at,
    )


async def _load_call_for_view(
    session: AsyncSession, caller: CallerContext, call_id: uuid.UUID
) -> AgentCall:
    """加载调用记录并做可见性校验。

    - 纯 admin / 非业务用户：403 admin_business_permission_denied（当前不返回
      系统元数据，口径见 README）。
    - 本人 / boss / 咨询总监：可见。
    - 其他业务用户：404（避免泄露不该见的调用记录）。
    """
    if not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "admin 无业务 Agent 调用可见权")
    call = (
        await session.execute(select(AgentCall).where(AgentCall.id == call_id))
    ).scalar_one_or_none()
    not_found = _denied(404, "agent_call_not_found", "调用记录不存在或不可见")
    if call is None:
        raise not_found
    if not _can_view_call(caller, call):
        raise not_found
    return call


async def _citations_of(session: AsyncSession, call_id: uuid.UUID) -> list[CitationOut]:
    """组装某调用的安全引用列表（带资产标题、scope、zone）。"""
    rows = list(
        (
            await session.execute(
                select(AgentCallCitation)
                .where(AgentCallCitation.call_id == call_id)
                .order_by(AgentCallCitation.citation_order)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return []
    asset_ids = {r.cited_asset_id for r in rows}
    asset_rows = (
        await session.execute(
            select(KnowledgeAsset.id, KnowledgeAsset.title, KnowledgeAsset.scope).where(
                KnowledgeAsset.id.in_(asset_ids)
            )
        )
    ).all()
    titles = {r[0]: r[1] for r in asset_rows}
    scopes = {r[0]: r[2] for r in asset_rows}
    return [
        CitationOut(
            asset_id=r.cited_asset_id,
            asset_title=titles.get(r.cited_asset_id, ""),
            scope=scopes.get(r.cited_asset_id, ""),
            cited_zone=r.cited_zone,
            used_access_layer=r.used_access_layer,
            is_pending_review=False,
            is_asset_zone=r.cited_zone == KnowledgeZone.asset.value,
            citation_order=r.citation_order,
            # 持久化的脱敏片段 / 安全序号可对外；server-only 的 chunk_ref 不读出。
            seq=r.cited_seq,
            snippet=r.cited_snippet,
        )
        for r in rows
    ]


async def get_agent_call(
    session: AsyncSession, caller: CallerContext, call_id: uuid.UUID
) -> AgentCallDetailResponse:
    """获取 Agent 调用记录（本人 / boss / 咨询总监）。不返回 Dify 内部标识。"""
    call = await _load_call_for_view(session, caller, call_id)
    citations = await _citations_of(session, call_id)
    # 提供人类可读名（治理展示用）。各一次主键查询，避免 N+1。
    caller_name = (
        await session.execute(select(User.name).where(User.id == call.caller_user_id))
    ).scalar_one_or_none() or ""
    project_name = (
        await session.execute(select(Project.name).where(Project.id == call.project_id))
    ).scalar_one_or_none() or ""
    return AgentCallDetailResponse(
        call_id=call.id,
        caller_user_id=call.caller_user_id,
        project_id=call.project_id,
        query_text=call.query_text,
        caller_name=caller_name,
        project_name=project_name,
        response_text=call.response_text,
        model_key=call.model_key,
        capability=call.capability,
        provider=call.provider,
        call_status=call.call_status,
        denied_reason=call.denied_reason,
        citations=citations,
        trace_id=call.trace_id,
        created_at=call.created_at,
    )


async def get_decision_items(
    session: AsyncSession, caller: CallerContext, call_id: uuid.UUID
) -> DecisionItemsResponse:
    """获取调用的候选项决策明细（治理解释）。

    过滤掉"不可发现"的候选（l5_not_discoverable / personal_asset_not_owned），
    避免通过 decision-items 反查 L5 / 他人个人知识的存在。
    """
    call = await _load_call_for_view(session, caller, call_id)
    decision = (
        await session.execute(
            select(AgentGatewayDecision).where(AgentGatewayDecision.call_id == call.id)
        )
    ).scalar_one_or_none()
    decision_status = decision.decision_status if decision is not None else "denied"

    rows = list(
        (
            await session.execute(
                select(AgentGatewayDecisionItem)
                .where(AgentGatewayDecisionItem.call_id == call.id)
                .order_by(AgentGatewayDecisionItem.created_at)
            )
        )
        .scalars()
        .all()
    )
    items = [
        DecisionItemOut(
            target_asset_id=r.target_asset_id,
            target_scope=r.target_scope,
            target_confidentiality_level=r.target_confidentiality_level,
            target_ai_access_level=r.target_ai_access_level,
            discovery_allowed=r.discovery_allowed,
            summary_allowed=r.summary_allowed,
            original_allowed=r.original_allowed,
            returned_layer=r.returned_layer,
            effective_access_source=r.effective_access_source,
            denied_reason=r.denied_reason,
        )
        for r in rows
        if r.denied_reason not in _LEAKY_DENIED_REASONS
    ]
    return DecisionItemsResponse(call_id=call.id, decision_status=decision_status, items=items)

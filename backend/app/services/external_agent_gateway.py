"""外部 Agent / 工作流网关编排。

把任意外部知识 / 工作流调用映射到检索原语（`AccessChannel.agent`）：
解析知识选择器 → scope/project → 解析真实平台调用人 → 同一套权限网关召回 →
裁剪为安全的 provider 中立 records（已脱敏证据 / 安全摘要，绝不原始 chunk）。

本模块**不依赖任何具体 provider**（Dify / Coze / 自研皆通过适配器调用本核心）。
provider 专属的请求 / 响应转译只存在于适配器（如 `app/api/dify.py`）。

强约束：
- **不发明 provider 超级用户**：必须解析出真实平台调用人，否则 fail closed（不检索）。
- 完全跟随调用人权限（`decide()`，channel=agent）：A4 原文降级、L5 不可发现、
  他人个人不可见、无权只给安全摘要——全部由权限网关收口。
- records 内容只可能是"已脱敏证据片段"或"安全业务摘要"，绝不未脱敏 WeKnora chunk。
- 响应 metadata 只放安全业务标识，绝不含 WeKnora kb/doc/chunk id、provider 内部标识、token。
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.enums import AuditAction, AuditLogType
from app.schemas.external_agent import ExternalRetrievalRecord
from app.schemas.permission import AccessChannel, CallerContext
from app.services import audit as audit_service
from app.services import retrieval
from app.services.desensitization import LlmOutputDesensitizer
from app.services.identity import load_user_with_roles
from app.services.llm_client import LLMClient, NullLLMClient
from app.services.permission import build_caller_context
from app.services.weknora_client import NullWeKnoraClient, WeKnoraClient

# 保密 / AI 级别序（用于注册行 max_* 天花板裁剪，作权限网关之上的额外收口）。
_CONF_RANK = {"L1": 1, "L2": 2, "L3": 3, "L4": 4, "L5": 5}
_AI_RANK = {"A1": 1, "A2": 2, "A3": 3, "A4": 4}


async def resolve_caller(
    session: AsyncSession, caller_user_id: uuid.UUID | None
) -> CallerContext | None:
    """解析真实平台调用人（fail closed）。无 id / 用户不存在 / 非 active → None。"""
    if caller_user_id is None:
        return None
    user = await load_user_with_roles(session, user_id=caller_user_id)
    if user is None or user.status != "active":
        return None
    return build_caller_context(user)


def parse_knowledge_selector(
    selector: str,
) -> tuple[str | None, uuid.UUID | None, uuid.UUID | None] | None:
    """解析知识选择器 → (scope, project_id, personal_owner)。非法 → None。

    provider 中立的安全选择器语法（适配器把 provider 专属 id 翻译成此形态）：

    - "all"            → (None, None, None)    # None scope = 并集
    - "company"        → ("company", None, None)
    - "project:<uuid>" → ("project", <uuid>, None)
    - "personal:<uuid>"→ ("personal", None, <uuid>)
    """
    kid = (selector or "").strip()
    if kid == "all":
        return None, None, None
    if kid == "company":
        return "company", None, None
    if kid.startswith("project:"):
        try:
            return "project", uuid.UUID(kid.split(":", 1)[1]), None
        except ValueError:
            return None
    if kid.startswith("personal:"):
        try:
            return "personal", None, uuid.UUID(kid.split(":", 1)[1])
        except ValueError:
            return None
    return None


def _within_ceiling(asset, max_conf: str, max_ai: str) -> bool:
    """注册行天花板裁剪：超过 max_confidentiality / max_ai 的资产丢弃（额外收口）。"""
    if _CONF_RANK.get(asset.confidentiality_level, 99) > _CONF_RANK.get(max_conf, 0):
        return False
    if _AI_RANK.get(asset.ai_access_level, 99) > _AI_RANK.get(max_ai, 0):
        return False
    return True


def _registry_allows(rule, scope, project_id, personal_owner) -> bool:
    """注册行 scope / project 天花板（在权限网关之上的额外收口，fail closed）。

    - allowed_scope=None/"all" → 不额外约束 scope；其余必须与请求 scope 匹配
      （company→company 请求，project→project 请求，personal→personal 请求）。
    - allowed_project_id 非空 → 仅允许该项目（project:<that uuid>）；company/personal/all
      或其它项目一律拒绝。
    未知 allowed_scope 值 → 保守拒绝。
    """
    allowed_scope = rule.allowed_scope
    if allowed_scope in (None, "all"):
        scope_ok = True
    elif allowed_scope == "company":
        scope_ok = scope == "company"
    elif allowed_scope == "project":
        scope_ok = project_id is not None
    elif allowed_scope == "personal":
        scope_ok = personal_owner is not None
    else:
        scope_ok = False  # 未知 scope 值，保守拒绝
    if rule.allowed_project_id is not None:
        return scope_ok and project_id == rule.allowed_project_id
    return scope_ok


def tool_scope_allowed(rule, req_scope: str | None) -> bool:
    """工具型调用的注册 scope 天花板（不落回 all）。"""
    allowed_scope = rule.allowed_scope
    if allowed_scope in (None, "all"):
        return True
    result: bool = (req_scope or "all") == allowed_scope
    return result


async def _kb_ids_for_request(
    session: AsyncSession, caller: CallerContext, rule, scope, project_id, personal_owner
) -> list[str]:
    """按解析后的约束确定可检索 KB 集（fail closed：越权约束 → 空集）。"""
    # 注册行 scope / project 天花板：冲突即空集（绝不返回更宽数据）。
    if not _registry_allows(rule, scope, project_id, personal_owner):
        return []
    if project_id is not None:
        # 项目知识：必须是该项目 active 成员（无项目身份不可经 Agent 访问项目库）。
        if project_id not in caller.active_project_ids:
            return []
        return await retrieval.resolve_project_kbs(session, project_id)
    if personal_owner is not None:
        # 个人知识：只能检索本人个人库（他人个人不可见）。
        if personal_owner != caller.user_id:
            return []
        return await retrieval.resolve_searchable_kbs(session, caller, "personal")
    # company / all：交给 KB 路由（其内部按调用人范围收口）。
    return await retrieval.resolve_searchable_kbs(session, caller, scope)


async def run_retrieval(
    session: AsyncSession,
    caller: CallerContext,
    rule,
    *,
    knowledge_selector: str,
    query: str,
    top_k: int,
    score_threshold: float,
    weknora: WeKnoraClient | NullWeKnoraClient,
    llm: LLMClient | NullLLMClient,
    trace_id: str | None,
) -> list[ExternalRetrievalRecord] | None:
    """外部知识检索 → 安全 records（provider 中立）。

    返回 None 表示知识选择器非法（适配器据此回 provider 专属"知识不存在"错误）。其余情况
    返回 records 列表（可能为空——无权 / 无命中均返回空，不泄露）。
    """
    parsed = parse_knowledge_selector(knowledge_selector)
    if parsed is None:
        return None
    scope, project_id, personal_owner = parsed

    kb_ids = await _kb_ids_for_request(session, caller, rule, scope, project_id, personal_owner)
    desens = LlmOutputDesensitizer(llm)
    recalled = await retrieval.recall_assets(
        session,
        caller,
        weknora,
        query=query,
        kb_ids=kb_ids,
        channel=AccessChannel.agent,
        trace_id=trace_id,
    )
    # 注册行天花板裁剪 + score 阈值（资产级 score）。
    recalled = [
        r
        for r in recalled
        if _within_ceiling(r.asset, rule.max_confidentiality_level, rule.max_ai_access_level)
        and r.score >= score_threshold
    ]
    # 放行+脱敏证据（discovery-only 无证据 → 不出 record；A4 original 降级为 summary 证据）。
    evidences = await retrieval.gather_evidence(recalled, desens, trace_id=trace_id)
    score_by_asset = {r.asset.id: r.score for r in recalled}

    records: list[ExternalRetrievalRecord] = []
    for order, e in enumerate(evidences, start=1):
        records.append(
            ExternalRetrievalRecord(
                content=e.snippet,  # 已脱敏证据 / 安全摘要，绝不未脱敏 chunk
                score=round(score_by_asset.get(e.asset.id, 0.0), 6),
                title=e.asset.title,
                metadata={
                    "asset_id": str(e.asset.id),
                    "scope": e.asset.scope,
                    "zone": e.asset.zone,
                    "used_access_layer": e.used_layer,
                    "citation_order": order,
                },
            )
        )
    records = records[: max(top_k, 0)] if top_k else records

    # 检索审计（operation；channel=agent，provider 来自注册行；只记安全元数据）。
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.knowledge_searched.value,
        trace_id=trace_id,
        target_type="external_agent_retrieval",
        extra={
            "channel": AccessChannel.agent.value,
            "provider": rule.provider,
            "record_count": len(records),
            "scope": scope or "all",
        },
        project_id=project_id,
    )
    await session.commit()
    return records

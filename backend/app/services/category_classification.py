"""Target-scoped, persisted AI suggestions for governed naming categories."""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import cast

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.identity import Project
from app.models.ingest import IngestTask, IngestTaskAiResult
from app.schemas.enums import IngestStatus, KnowledgeScope
from app.schemas.naming import (
    CategoryClassificationBatchRequest,
    CategoryClassificationBatchResponse,
    CategoryClassificationItemResponse,
    ManualCategorySelectionRequest,
    NamingOptionItem,
)
from app.schemas.permission import CallerContext
from app.services import llm_usage, naming_rules
from app.services.llm_client import LLMClient, LLMError, NullLLMClient

_CLASSIFICATION_BATCH_SIZE = 20
_CLASSIFICATION_MAX_OUTPUT_TOKENS = 1_800
_CLASSIFICATION_MAX_INPUT_CHARS = 20_000
_CLASSIFICATION_CONCURRENCY = 8
_RELIABLE_CONFIDENCE = {"high", "medium"}
_PENDING_STATUSES = {
    IngestStatus.pending_confirmation.value,
    IngestStatus.failed.value,
    IngestStatus.rejected.value,
    IngestStatus.waiting_review.value,
}


def _denied(status: int, reason: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"denied_reason": reason, "message": message})


@dataclass(frozen=True, slots=True)
class _CandidateContext:
    revision: int | None
    target_label: str
    candidates: list[NamingOptionItem]


async def _candidate_context(
    session: AsyncSession,
    caller: CallerContext,
    scope: KnowledgeScope,
    project_id: uuid.UUID | None,
) -> _CandidateContext:
    options = await naming_rules.options(session, caller, scope, project_id)
    if scope == KnowledgeScope.project:
        project = await session.get(Project, project_id)
        target_label = f"项目知识库 / {project.name}" if project is not None else "项目知识库"
    else:
        target_label = "公司知识库"
    # Category classification was retired in favor of explicit formal-directory
    # selection.  Keep this legacy service fail-closed for historical callers
    # without reintroducing the removed category field on the public contract.
    return _CandidateContext(options.rule_version, target_label, [])


def _stored(ai: IngestTaskAiResult | None) -> dict | None:
    fields = ai.naming_parsed_fields if ai and isinstance(ai.naming_parsed_fields, dict) else {}
    value = fields.get("category_suggestion")
    return value if isinstance(value, dict) else None


def _persist(ai: IngestTaskAiResult, value: dict) -> None:
    fields = dict(ai.naming_parsed_fields or {})
    fields["category_suggestion"] = value
    ai.naming_parsed_fields = fields


async def _lock_ai_result(
    session: AsyncSession, ai_result_id: uuid.UUID
) -> IngestTaskAiResult | None:
    result = await session.scalar(
        select(IngestTaskAiResult)
        .where(IngestTaskAiResult.id == ai_result_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return cast(IngestTaskAiResult | None, result)


def _response(task_id: uuid.UUID, value: dict) -> CategoryClassificationItemResponse:
    return CategoryClassificationItemResponse(
        task_id=task_id,
        suggested_category_id=value.get("suggested_category_id"),
        category_source=value["category_source"],
        category_confidence=value["category_confidence"],
        category_reason=value["category_reason"],
        candidate_rule_revision=value.get("candidate_rule_revision"),
        status=value["status"],
        retryable=bool(value.get("retryable")),
    )


def _manual_value(reason: str, revision: int | None, *, failed: bool = False) -> dict:
    return {
        "suggested_category_id": None,
        "category_source": "needs_manual",
        "category_confidence": "low",
        "category_reason": reason[:300],
        "candidate_rule_revision": revision,
        "status": "failed" if failed else "needs_manual",
        "retryable": failed,
    }


def _matches_category_context(
    value: dict,
    *,
    revision: int | None,
    target_scope: str,
    target_project_id: str | None,
    candidate_ids: set[str],
) -> bool:
    category_id = str(value.get("suggested_category_id") or "")
    source = value.get("category_source")
    category_matches = (
        not category_id or category_id in candidate_ids
        if source == "needs_manual"
        else bool(category_id and category_id in candidate_ids)
    )
    return bool(
        value.get("candidate_rule_revision") == revision
        and value.get("target_scope") == target_scope
        and value.get("target_project_id") == target_project_id
        and category_matches
    )


def _authorized(
    task: IngestTask, caller: CallerContext, request: CategoryClassificationBatchRequest
) -> bool:
    if task.status not in _PENDING_STATUSES or task.result_asset_id is not None:
        return False
    if not (task.created_by == caller.user_id or caller.can_discover_l5):
        return False
    scope = request.target_scope.value
    if task.target_scope and task.target_scope != scope:
        return False
    if task.target_project_id and task.target_project_id != request.target_project_id:
        return False
    return True


def _prompt(
    candidates: list[NamingOptionItem], evidence: dict[str, object], revision: int
) -> list[dict[str, str]]:
    allowed = [
        {
            "id": str(item.id),
            "scope": item.scope,
            "primary": item.primary,
            "secondary": item.secondary,
            "display_name": f"{item.primary} / {item.secondary}",
            "description": item.description,
            "enabled": True,
            "sort_order": item.sort_order,
        }
        for index, item in enumerate(candidates)
    ]
    system = (
        "你是受控目录分类器。只能依据受限语义草稿，从候选列表选择一个 id；"
        "不得依据文件名、项目代码、历史一级/二级类别或‘交付成果’等旧命名片段。"
        "不确定时 suggested_category_id 必须为 null，禁止猜测或创造类别。"
        "仅返回 JSON：suggested_category_id、category_confidence(high/medium/low)。"
    )
    user = json.dumps(
        {"candidate_rule_revision": revision, "candidates": allowed, "semantic_draft": evidence},
        ensure_ascii=False,
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def _classify_one(
    llm: LLMClient | NullLLMClient,
    semaphore: asyncio.Semaphore,
    ai: IngestTaskAiResult,
    candidates: list[NamingOptionItem],
    revision: int,
    trace_id: str | None,
) -> dict:
    evidence = _batch_evidence(ai)
    if evidence is None:
        return _manual_value("缺少可复用的 AI 摘要，请人工选择目录类别", revision)
    if isinstance(llm, NullLLMClient) or not getattr(llm, "provider", ""):
        return _manual_value("AI 分类服务未配置，请人工选择目录类别", revision, failed=True)
    async with semaphore:
        try:
            raw = await llm.chat_completion(
                _prompt(candidates, evidence, revision),
                trace_id=trace_id,
            )
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("category classifier response must be a JSON object")
        except (LLMError, json.JSONDecodeError, TypeError, ValueError):
            return _manual_value("AI 分类暂时失败，请重试或人工选择", revision, failed=True)
    allowed = {str(item.id): item.id for item in candidates}
    category_id = str(parsed.get("suggested_category_id") or "")
    confidence = str(parsed.get("category_confidence") or "low").lower()
    if category_id not in allowed or confidence not in _RELIABLE_CONFIDENCE:
        return _manual_value("AI 未能可靠判断，请人工选择目录类别", revision)
    return {
        "suggested_category_id": str(allowed[category_id]),
        "category_source": "ai_content",
        "category_confidence": confidence,
        "category_reason": "AI 根据正文语义匹配当前目标的目录规则",
        "candidate_rule_revision": revision,
        "status": "classified",
        "retryable": False,
    }


async def _classify_batch_legacy(
    session: AsyncSession,
    caller: CallerContext,
    request: CategoryClassificationBatchRequest,
    llm: LLMClient | NullLLMClient,
    trace_id: str | None,
) -> CategoryClassificationBatchResponse:
    context = await _candidate_context(
        session, caller, request.target_scope, request.target_project_id
    )
    tasks = (
        (
            await session.execute(
                select(IngestTask)
                .where(IngestTask.id.in_(request.task_ids))
                .options(selectinload(IngestTask.ai_result))
            )
        )
        .scalars()
        .all()
    )
    by_id = {task.id: task for task in tasks}
    results: dict[uuid.UUID, dict] = {}
    pending: list[tuple[IngestTask, IngestTaskAiResult]] = []
    candidate_ids = {str(item.id) for item in context.candidates}

    for task_id in request.task_ids:
        task = by_id.get(task_id)
        if task is None or not _authorized(task, caller, request) or task.ai_result is None:
            results[task_id] = _manual_value("该资料当前不可分类", context.revision)
            continue
        old = _stored(task.ai_result)
        old_id = str(old.get("suggested_category_id")) if old else ""
        old_current = bool(
            old
            and old.get("candidate_rule_revision") == context.revision
            and old.get("target_scope") == request.target_scope.value
            and old.get("target_project_id")
            == (str(request.target_project_id) if request.target_project_id else None)
            and (not old_id or old_id in candidate_ids)
        )
        if old_current and old is not None:
            if old.get("category_source") == "manual":
                results[task_id] = old
                continue
            if old.get("category_source") in {"ai_content", "rule_only_option"}:
                results[task_id] = old
                continue
            if old.get("category_source") == "needs_manual" and not request.retry:
                results[task_id] = old
                continue
        if not context.candidates:
            value = _manual_value("当前目标尚未配置启用的目录类别", context.revision)
            results[task_id] = value
            continue
        if len(context.candidates) == 1:
            value = {
                "suggested_category_id": str(context.candidates[0].id),
                "category_source": "rule_only_option",
                "category_confidence": "high",
                "category_reason": "当前规则只有一个启用目录类别",
                "candidate_rule_revision": context.revision,
                "status": "classified",
                "retryable": False,
            }
            results[task_id] = value
            continue
        pending.append((task, task.ai_result))

    if pending and context.revision is not None:
        semaphore = asyncio.Semaphore(_CLASSIFICATION_CONCURRENCY)
        values = await asyncio.gather(
            *[
                _classify_one(
                    llm,
                    semaphore,
                    ai,
                    context.candidates,
                    context.revision,
                    trace_id,
                )
                for _, ai in pending
            ]
        )
        for (task, _ai), value in zip(pending, values, strict=True):
            results[task.id] = value

    target_project = str(request.target_project_id) if request.target_project_id else None
    for task_id in sorted(results, key=str):
        value = dict(results[task_id])
        value["target_scope"] = request.target_scope.value
        value["target_project_id"] = target_project
        task = by_id.get(task_id)
        if task is not None and task.ai_result is not None:
            locked_ai = await _lock_ai_result(session, task.ai_result.id)
            if locked_ai is None:
                continue
            current = _stored(locked_ai)
            if current and current.get("category_source") == "manual":
                results[task_id] = current
                continue
            _persist(locked_ai, value)
        results[task_id] = value
    await session.commit()
    return CategoryClassificationBatchResponse(
        target_label=context.target_label,
        candidate_rule_revision=context.revision,
        candidate_count=len(context.candidates),
        items=[_response(task_id, results[task_id]) for task_id in request.task_ids],
    )


async def save_manual_selection(
    session: AsyncSession,
    caller: CallerContext,
    task_id: uuid.UUID,
    request: ManualCategorySelectionRequest,
) -> CategoryClassificationItemResponse:
    batch_request = CategoryClassificationBatchRequest(
        task_ids=[task_id],
        target_scope=request.target_scope,
        target_project_id=request.target_project_id,
    )
    context = await _candidate_context(
        session, caller, request.target_scope, request.target_project_id
    )
    category = next((item for item in context.candidates if item.id == request.category_id), None)
    if category is None:
        raise _denied(409, "naming_category_unavailable", "目录类别已停用或不适用于当前目标")
    task = await session.scalar(
        select(IngestTask)
        .where(IngestTask.id == task_id)
        .options(selectinload(IngestTask.ai_result))
    )
    if task is None or not _authorized(task, caller, batch_request) or task.ai_result is None:
        raise _denied(404, "ingest_task_not_found", "该资料当前不可操作")
    locked_ai = await _lock_ai_result(session, task.ai_result.id)
    if locked_ai is None:
        raise _denied(404, "ingest_task_not_found", "该资料当前不可操作")
    value = {
        "suggested_category_id": str(category.id),
        "category_source": "manual",
        "category_confidence": "high",
        "category_reason": "人工已选择",
        "candidate_rule_revision": context.revision,
        "target_scope": request.target_scope.value,
        "target_project_id": str(request.target_project_id) if request.target_project_id else None,
        "status": "classified",
        "retryable": False,
    }
    _persist(locked_ai, value)
    await session.commit()
    return _response(task_id, value)


# Cost-governed classifier.  This later definition intentionally replaces the
# legacy per-document implementation above while keeping the manual-selection
# API and its persistence safeguards unchanged.
def _batch_evidence(ai: IngestTaskAiResult) -> dict[str, object] | None:
    """Classification consumes the first-pass draft, never extracted_text."""
    one_liner = (ai.suggested_one_liner or "").strip()[:240]
    summary = (ai.suggested_summary or "").strip()[:1_000]
    key_points = [str(item).strip()[:100] for item in (ai.suggested_key_points or [])]
    key_points = [item for item in key_points if item][:6]
    if not (one_liner or summary or key_points):
        return None
    return {"one_liner": one_liner, "summary": summary, "key_points": key_points}


def _batch_prompt(
    candidates: list[NamingOptionItem],
    documents: list[tuple[uuid.UUID, dict[str, object]]],
    revision: int,
) -> list[dict[str, str]]:
    allowed = [
        {
            "id": str(item.id),
            "display_name": f"{item.primary} / {item.secondary}",
            "description": (item.description or "")[:160] or None,
            "sort_order": item.sort_order,
        }
        for item in candidates
    ]
    system = (
        "You are a governed document classifier. Select only an id in candidates, "
        "based only on each document's supplied semantic draft. Do not infer from filenames, "
        "project codes, or historical naming. If uncertain, return null. Return JSON object "
        "{items:[{task_id,suggested_category_id,category_confidence}]}; confidence is high, medium, or low."
    )
    user = json.dumps(
        {
            "candidate_rule_revision": revision,
            "candidates": allowed,
            "documents": [{"task_id": str(task_id), **evidence} for task_id, evidence in documents],
        },
        ensure_ascii=False,
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _prompt_chars(messages: list[dict[str, str]]) -> int:
    return sum(len(message["content"]) for message in messages)


def _classification_chunks(
    items: list[tuple[IngestTask, dict[str, object]]],
    candidates: list[NamingOptionItem],
    revision: int,
) -> tuple[list[list[tuple[IngestTask, dict[str, object]]]], list[IngestTask]]:
    """Build complete JSON requests within both item-count and character budgets."""
    chunks: list[list[tuple[IngestTask, dict[str, object]]]] = []
    overflow: list[IngestTask] = []
    current: list[tuple[IngestTask, dict[str, object]]] = []
    for item in items:
        trial = [*current, item]
        trial_messages = _batch_prompt(
            candidates,
            [(task.id, evidence) for task, evidence in trial],
            revision,
        )
        if (
            len(trial) <= _CLASSIFICATION_BATCH_SIZE
            and _prompt_chars(trial_messages) <= _CLASSIFICATION_MAX_INPUT_CHARS
        ):
            current = trial
            continue
        if current:
            chunks.append(current)
            current = []
        single_messages = _batch_prompt(candidates, [(item[0].id, item[1])], revision)
        if _prompt_chars(single_messages) <= _CLASSIFICATION_MAX_INPUT_CHARS:
            current = [item]
        else:
            overflow.append(item[0])
    if current:
        chunks.append(current)
    return chunks, overflow


def _batch_parsed_value(parsed: object, candidates: list[NamingOptionItem], revision: int) -> dict:
    if not isinstance(parsed, dict):
        return _manual_value("AI 分类结果无效，请重试或人工选择", revision, failed=True)
    allowed = {str(item.id): item.id for item in candidates}
    category_id = str(parsed.get("suggested_category_id") or "")
    confidence = str(parsed.get("category_confidence") or "low").lower()
    if category_id not in allowed or confidence not in _RELIABLE_CONFIDENCE:
        return _manual_value("AI 未能可靠判断，请人工选择目录类别", revision)
    return {
        "suggested_category_id": str(allowed[category_id]),
        "category_source": "ai_content",
        "category_confidence": confidence,
        "category_reason": "AI 根据首次生成的摘要与关键点匹配当前目标的目录规则",
        "candidate_rule_revision": revision,
        "status": "classified",
        "retryable": False,
    }


async def _classify_chunk(
    session: AsyncSession,
    llm: LLMClient | NullLLMClient,
    items: list[tuple[IngestTask, dict[str, object]]],
    candidates: list[NamingOptionItem],
    revision: int,
    trace_id: str | None,
) -> dict[uuid.UUID, dict]:
    if isinstance(llm, NullLLMClient) or not getattr(llm, "provider", ""):
        return {
            task.id: _manual_value("AI 分类服务未配置，请人工选择目录类别", revision, failed=True)
            for task, _evidence in items
        }
    try:
        raw = await llm.chat_completion(
            _batch_prompt(candidates, [(task.id, evidence) for task, evidence in items], revision),
            max_input_chars=_CLASSIFICATION_MAX_INPUT_CHARS,
            max_tokens=_CLASSIFICATION_MAX_OUTPUT_TOKENS,
            trace_id=trace_id,
        )
        payload = json.loads(raw)
        returned = payload.get("items") if isinstance(payload, dict) else None
        # Accept the legacy single-item contract during rollout. Production
        # batches always use the items array above.
        if not isinstance(returned, list) and len(items) == 1 and isinstance(payload, dict):
            returned = [{"task_id": str(items[0][0].id), **payload}]
        if not isinstance(returned, list):
            raise ValueError("items missing")
    except (LLMError, json.JSONDecodeError, TypeError, ValueError):
        await llm_usage.record(
            session,
            scenario="category_classification",
            provider=getattr(llm, "provider", None),
            model=getattr(llm, "model", None),
            batch_size=len(items),
            cache_status="miss",
            outcome="failure",
            usage=getattr(llm, "last_usage", None),
        )
        return {
            task.id: _manual_value("AI 分类暂时失败，请重试或人工选择", revision, failed=True)
            for task, _evidence in items
        }
    await llm_usage.record(
        session,
        scenario="category_classification",
        provider=getattr(llm, "provider", None),
        model=getattr(llm, "model", None),
        batch_size=len(items),
        cache_status="miss",
        outcome="success",
        usage=getattr(llm, "last_usage", None),
    )
    by_id = {str(item.get("task_id")): item for item in returned if isinstance(item, dict)}
    return {
        task.id: _batch_parsed_value(by_id[str(task.id)], candidates, revision)
        if str(task.id) in by_id
        else _manual_value("AI 未返回该资料的分类结果，请重试或人工选择", revision, failed=True)
        for task, _evidence in items
    }


async def classify_batch(
    session: AsyncSession,
    caller: CallerContext,
    request: CategoryClassificationBatchRequest,
    llm: LLMClient | NullLLMClient,
    trace_id: str | None,
) -> CategoryClassificationBatchResponse:
    """Reuse persisted results and classify only missing items in bounded chunks."""
    context = await _candidate_context(
        session, caller, request.target_scope, request.target_project_id
    )
    tasks = (
        (
            await session.execute(
                select(IngestTask)
                .where(IngestTask.id.in_(request.task_ids))
                .options(selectinload(IngestTask.ai_result))
            )
        )
        .scalars()
        .all()
    )
    by_id = {task.id: task for task in tasks}
    results: dict[uuid.UUID, dict] = {}
    pending: list[tuple[IngestTask, dict[str, object]]] = []
    candidate_ids = {str(item.id) for item in context.candidates}
    target_project = str(request.target_project_id) if request.target_project_id else None
    cached_count = 0

    for task_id in request.task_ids:
        task = by_id.get(task_id)
        if task is None or not _authorized(task, caller, request) or task.ai_result is None:
            results[task_id] = _manual_value("该资料当前不可分类", context.revision)
            continue
        old = _stored(task.ai_result)
        fingerprint = (
            llm_usage.cache_fingerprint(
                content_hash=task.source_file_hash,
                scope=request.target_scope.value,
                project_id=target_project,
                rule_revision=context.revision,
                provider=getattr(llm, "provider", ""),
                model=getattr(llm, "model", ""),
            )
            if task.source_file_hash and context.revision is not None
            else None
        )
        current = bool(
            old
            and _matches_category_context(
                old,
                revision=context.revision,
                target_scope=request.target_scope.value,
                target_project_id=target_project,
                candidate_ids=candidate_ids,
            )
        )
        if current and old is not None:
            source = old.get("category_source")
            reusable = source in {"manual", "rule_only_option"} or (
                source in {"ai_content", "needs_manual"}
                and old.get("cache_fingerprint") == fingerprint
                and (source != "needs_manual" or not request.retry)
            )
            if reusable:
                results[task_id] = old
                cached_count += 1
                continue
        if old and old.get("category_source") == "manual":
            results[task_id] = _manual_value(
                "原人工目录类别已不适用于当前目标或规则，请重新人工选择",
                context.revision,
            )
            continue
        fields = (
            task.ai_result.naming_parsed_fields
            if isinstance(task.ai_result.naming_parsed_fields, dict)
            else {}
        )
        by_scope = fields.get("category_suggestions_by_scope")
        provisional = (
            by_scope.get(request.target_scope.value) if isinstance(by_scope, dict) else None
        )
        provisional_id = (
            str(provisional.get("suggested_category_id") or "")
            if isinstance(provisional, dict)
            else ""
        )
        provisional_cache = (
            llm_usage.cache_fingerprint(
                content_hash=task.source_file_hash,
                scope="pending_selection",
                project_id=None,
                rule_revision=context.revision,
                provider=getattr(llm, "provider", ""),
                model=getattr(llm, "model", ""),
            )
            if task.source_file_hash and context.revision is not None
            else None
        )
        if (
            isinstance(provisional, dict)
            and provisional.get("candidate_rule_revision") == context.revision
            and provisional.get("candidate_fingerprint")
            == llm_usage.candidate_fingerprint(sorted(candidate_ids))
            and provisional.get("cache_fingerprint") == provisional_cache
            and (not provisional_id or provisional_id in candidate_ids)
            and (
                provisional.get("category_source") == "ai_content"
                or (provisional.get("category_source") == "needs_manual" and not request.retry)
            )
        ):
            results[task_id] = provisional
            cached_count += 1
            continue
        if not context.candidates:
            results[task_id] = _manual_value("当前目标尚未配置启用的目录类别", context.revision)
            continue
        if len(context.candidates) == 1:
            results[task_id] = {
                "suggested_category_id": str(context.candidates[0].id),
                "category_source": "rule_only_option",
                "category_confidence": "high",
                "category_reason": "当前规则只有一个启用目录类别",
                "candidate_rule_revision": context.revision,
                "status": "classified",
                "retryable": False,
            }
            continue
        evidence = _batch_evidence(task.ai_result)
        if evidence is None:
            results[task_id] = _manual_value(
                "缺少可复用的 AI 摘要，请人工选择目录类别", context.revision
            )
            continue
        pending.append((task, evidence))

    if context.revision is not None:
        chunks, overflow = _classification_chunks(pending, context.candidates, context.revision)
        for task in overflow:
            results[task.id] = _manual_value(
                "目录候选上下文超过安全输入预算，请调整规则或人工选择",
                context.revision,
                failed=True,
            )
        for chunk in chunks:
            results.update(
                await _classify_chunk(
                    session,
                    llm,
                    chunk,
                    context.candidates,
                    context.revision,
                    trace_id,
                )
            )

    if cached_count:
        await llm_usage.record(
            session,
            scenario="category_classification",
            provider=getattr(llm, "provider", None),
            model=getattr(llm, "model", None),
            batch_size=cached_count,
            cache_status="hit",
            outcome="cache_hit",
        )

    for task_id in request.task_ids:
        value = dict(results[task_id])
        value["target_scope"] = request.target_scope.value
        value["target_project_id"] = target_project
        task = by_id.get(task_id)
        if (
            task is not None
            and task.source_file_hash
            and context.revision is not None
            and value.get("category_source") != "manual"
        ):
            value["model_ref"] = llm_usage.safe_model_ref(
                getattr(llm, "provider", None), getattr(llm, "model", None)
            )
            value["cache_fingerprint"] = llm_usage.cache_fingerprint(
                content_hash=task.source_file_hash,
                scope=request.target_scope.value,
                project_id=target_project,
                rule_revision=context.revision,
                provider=getattr(llm, "provider", ""),
                model=getattr(llm, "model", ""),
            )
        if task is not None and task.ai_result is not None:
            locked = await _lock_ai_result(session, task.ai_result.id)
            if locked is not None:
                stored = _stored(locked)
                if stored and stored.get("category_source") == "manual":
                    if _matches_category_context(
                        stored,
                        revision=context.revision,
                        target_scope=request.target_scope.value,
                        target_project_id=target_project,
                        candidate_ids=candidate_ids,
                    ):
                        results[task_id] = stored
                    else:
                        results[task_id] = _manual_value(
                            "原人工目录类别已不适用于当前目标或规则，请重新人工选择",
                            context.revision,
                        )
                    continue
                _persist(locked, value)
        results[task_id] = value
    await session.commit()
    return CategoryClassificationBatchResponse(
        target_label=context.target_label,
        candidate_rule_revision=context.revision,
        candidate_count=len(context.candidates),
        items=[_response(task_id, results[task_id]) for task_id in request.task_ids],
    )

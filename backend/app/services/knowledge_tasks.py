"""Private delegations with server-owned tools and expiring execution claims."""

import asyncio
import json
import logging
import uuid
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.db.utils import utc_now
from app.models.identity import Project
from app.models.knowledge_task import KnowledgeTask
from app.models.maintenance_agent import MaintenancePolicy
from app.schemas.knowledge_task import TaskDetail, TaskRow
from app.services import knowledge_task_tools as tools
from app.services import maintenance_access as access
from app.services.generation_models import resolve_generation_llm_client
from app.services.llm_client import LLMError, NullLLMClient


async def scope(session, caller, key):
    project_id = access.parse_key(key)
    if (
        not caller
        or not caller.is_active
        or not caller.is_business_user
        or not caller.active_company_role
    ):
        raise access.reject(403)
    if project_id:
        project = await session.get(Project, project_id)
        if (
            project_id not in caller.active_project_ids
            or not project
            or project.status == "archived"
            or key != f"project:{project_id}"
        ):
            raise access.reject()
    return project_id


def owned(caller, key):
    return and_(
        KnowledgeTask.user_id == caller.user_id,
        KnowledgeTask.role == caller.active_company_role,
        KnowledgeTask.library_key == key,
    )


async def create(session, caller, key, cmd):
    await scope(session, caller, key)
    row = KnowledgeTask(
        id=cmd.request_id,
        user_id=caller.user_id,
        role=caller.active_company_role,
        library_key=key,
        instruction=cmd.instruction,
    )
    session.add(row)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        row = await session.scalar(
            select(KnowledgeTask).where(KnowledgeTask.id == cmd.request_id, owned(caller, key))
        )
        if not row or row.instruction != cmd.instruction:
            raise access.reject(409, "任务标识已使用，请重新交代任务") from None
    return TaskRow.model_validate(row, from_attributes=True)


async def recent(session, caller, key):
    await scope(session, caller, key)
    return list(
        await session.scalars(
            select(KnowledgeTask)
            .where(owned(caller, key))
            .order_by(KnowledgeTask.created_at.desc(), KnowledgeTask.id)
            .limit(20)
        )
    )


async def detail(session, caller, key, task_id):
    await scope(session, caller, key)
    task = await session.scalar(
        select(KnowledgeTask).where(KnowledgeTask.id == task_id, owned(caller, key))
    )
    if not task:
        raise access.reject()
    result = task.result
    availability, evidence = (
        await tools.evidence(session, caller, key, result["selected"], task.instruction)
        if result.get("selected")
        else (None, None)
    )
    return TaskDetail(
        **TaskRow.model_validate(task, from_attributes=True).model_dump(),
        mode=result.get("mode"),
        failure_reason=result.get("failure_reason"),
        candidates=result.get("candidates", 0),
        inspected=result.get("inspected", 0),
        availability=availability,
        evidence=evidence,
    )


def claimable():
    return or_(
        KnowledgeTask.status == "queued",
        and_(
            KnowledgeTask.status.in_(["searching", "checking"]),
            KnowledgeTask.lease_until < utc_now(),
        ),
    )


async def recover(maker):
    async with maker() as session:
        ids = list(
            await session.scalars(
                select(KnowledgeTask.id)
                .where(claimable())
                .order_by(KnowledgeTask.created_at)
                .limit(3)
            )
        )
    for task_id in ids:
        await execute(maker, task_id)


async def checkpoint(session, task_id, claim, status, result, *, final=False):
    changed = await session.execute(
        update(KnowledgeTask)
        .where(KnowledgeTask.id == task_id, KnowledgeTask.claim == claim)
        .values(
            status=status,
            result=result,
            claim=None if final else claim,
            lease_until=None if final else utc_now() + timedelta(minutes=3),
        )
    )
    await session.commit()
    return changed.rowcount == 1


async def decide_step(client, goals, observations, checked):
    """The model can inspect a numbered candidate or finish with one it has checked."""
    response = await asyncio.wait_for(
        client.chat_completion(
            [
                {
                    "role": "system",
                    "content": "为顾问选一份匹配任务且可复用的当前资料。根据匿名的条件匹配、原文权限、版本核对结果选择下一步。优先覆盖更多条件、可打开且有效的资料。可比较其他候选，再选已核对为有效的候选。只输出 JSON，action 为 inspect、recommend 或 abstain，index 为从 0 开始的候选号。",
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "requested_actions": goals,
                            "candidates": observations,
                            "version_checks": checked,
                        }
                    ),
                },
            ],
            temperature=0,
            max_tokens=100,
        ),
        timeout=12,
    )
    data = json.loads(response)
    if not isinstance(data, dict):
        raise ValueError()
    action, i = data.get("action"), data.get("index")
    if action == "abstain":
        return action, None
    if type(i) is not int or not 0 <= i < len(observations):
        raise ValueError()
    if (action == "inspect" and i not in checked) or (
        action == "recommend" and checked.get(i, {}).get("current")
    ):
        return action, i
    raise ValueError()


async def run_tools(session, task, claim):
    caller = await access.actor_context(session, task.user_id, task.role)
    project = await scope(session, caller, task.library_key)
    choices = await tools.search(session, caller, task.library_key, task.instruction)
    result = {"candidates": len(choices), "inspected": 0, "mode": "catalog"}
    if not choices:
        return "empty", result
    checked, selections = {}, {}
    observations = [facts for _, facts in choices]
    goals = [
        code
        for code, phrases in (
            ("compare_versions", ("新版", "版本", "对比", "差异")),
            ("reuse_document", ("模板", "原文", "能用", "拿来用", "复用")),
            ("read_summary", ("摘要", "概览", "大意")),
        )
        if any(phrase in task.instruction for phrase in phrases)
    ]
    # At most one inspection per candidate and one final selection. Recheck authority
    # and selected model before every external call; send no names, text, IDs or URLs.
    for _ in range(len(choices) + 1):
        policy = await session.scalar(
            select(MaintenancePolicy)
            .where(MaintenancePolicy.library_key == task.library_key)
            .execution_options(populate_existing=True)
        )
        client = None
        if policy and policy.content_authorized and result["mode"] != "model_unavailable":
            grantor = await access.actor_context(
                session, policy.authorized_by, policy.authorized_role
            )
            if grantor and access.library_allowed(grantor, project):
                client = await resolve_generation_llm_client(
                    session, model_ref=policy.settings.get("model_ref", "system_default")
                )
        if not await checkpoint(session, task.id, claim, "checking", result):
            return "failed", result
        step = None
        if client and not isinstance(client, NullLLMClient):
            try:
                step = await decide_step(client, goals, observations, checked)
                result["mode"] = "model"
            except (TimeoutError, LLMError, ValueError, TypeError):
                result["mode"] = "model_unavailable"
        elif isinstance(client, NullLLMClient):
            result["mode"] = "model_unavailable"
        if step is None:
            if selections:
                step = ("recommend", next(iter(selections)))
            else:
                i = next((j for j in range(len(choices)) if j not in checked), None)
                step = ("inspect", i) if i is not None else ("abstain", None)
        action, i = step
        if action == "abstain":
            return "empty", result
        if action == "recommend":
            result["selected"] = selections[i]
            return "ready", result
        caller = await access.actor_context(session, task.user_id, task.role)
        await scope(session, caller, task.library_key)
        info = await tools.inspect(session, caller, task.library_key, choices[i][0])
        checked[i] = {"current": bool(info)}
        if info:
            doc, current, history = info
            names, from_summary, _ = tools.match_evidence(doc, tools.phrases(task.instruction))
            if names or from_summary:
                selections[i] = {"asset_id": str(doc.id), "version_id": current["version_id"]}
                checked[i].update(
                    original=doc.access_info.original,
                    needs_update=doc.asset_status == "needs_update",
                    visible_versions=len(history["items"]),
                )
            else:
                checked[i]["current"] = False
        result["inspected"] = len(checked)
    return "empty", result


async def execute(maker, task_id):
    claim = uuid.uuid4()
    async with maker() as session:
        taken = await session.execute(
            update(KnowledgeTask)
            .where(KnowledgeTask.id == task_id, claimable())
            .values(status="searching", claim=claim, lease_until=utc_now() + timedelta(minutes=3))
        )
        await session.commit()
        if not taken.rowcount:
            return
        task = await session.get(KnowledgeTask, task_id)
        try:
            status, result = await run_tools(session, task, claim)
        except Exception as exc:
            await session.rollback()
            reason = (
                "access_changed"
                if isinstance(exc, HTTPException) and exc.status_code in {403, 404}
                else "tool_error"
            )
            logging.getLogger(__name__).warning(
                "knowledge_task_failed", extra={"failure_reason": reason}
            )
            status, result = "failed", {"failure_reason": reason}
        await checkpoint(session, task_id, claim, status, result, final=True)

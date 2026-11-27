"""Knowledge-maintenance tools for the shared workspace execution loop.

Handlers never commit: the harness commits the fenced action receipt, checkpoint
and business effects together. Model arguments cannot grant authority or confirm
an action. Long scans return a durable observation handle instead of claiming a
completed task. Inspection remains in the existing scan workers.
"""

import uuid

from fastapi import HTTPException
from sqlalchemy import select

from app.core.personal_information import redact_personal_data, redact_personal_information
from app.db.utils import utc_now
from app.models.knowledge import KnowledgeAsset
from app.models.maintenance_agent import (
    MaintenanceIssue,
    MaintenanceIssueEvent,
    MaintenancePolicy,
    MaintenanceRun,
)
from app.schemas.enums import AuditLogType
from app.schemas.maintenance_agent import IssueCommand, ScanSettings
from app.services import audit, knowledge_workspace_tools, workspace_tools
from app.services import maintenance_access as access
from app.services import maintenance_agent as maintenance
from app.services.maintenance_jobs import _digest
from app.services.maintenance_reports import assess_scope, project_detail
from app.services.maintenance_rules import ACTIVE, RULES, SUGGESTIONS, digest
from app.services.permission import knowledge_maintainer_allowed

ACTIVE_RUNS = {"queued", "running"}
MUTATIONS = {
    "start_maintenance_scan",
    "follow_maintenance_issue",
    "request_maintenance_recheck",
    "notify_maintenance_issue",
}
CATEGORIES = {"integrity", "availability", "maintenance", "duplicates", "quality", "privacy"}
ISSUE_STATUSES = ACTIVE | {
    "all",
    "active",
    "resolved",
    "false_positive",
    "snoozed",
    "not_applicable",
}


def definitions():
    """The same closed registry is used for model declarations and dispatch."""
    identifier = {"type": "string", "format": "uuid"}
    specs = [
        (
            "inspect_knowledge_asset",
            "核对资料版本",
            "按当前阅读权限核对资料有效版本、已采纳换版、脱敏摘要差异和旧版引用；不读未授权原文",
            {"asset_id": identifier},
        ),
        (
            "maintenance_overview",
            "盘点知识库",
            "查看所选非个人知识库的巡检范围、配置状态和现有问题概况",
            {},
        ),
        (
            "list_maintenance_issues",
            "查看维护问题",
            "按当前维护权限分页列出问题；不能据此断言全库已检查",
            {
                "page": {"type": "integer", "minimum": 1},
                "category": {"type": "string", "enum": sorted(CATEGORIES)},
                "status": {"type": "string", "enum": sorted(ISSUE_STATUSES)},
            },
        ),
        (
            "inspect_maintenance_issue",
            "核对问题与版本",
            "核对具体问题的当前版本、脱敏证据定位和处理建议",
            {"issue_id": identifier},
        ),
        (
            "start_maintenance_scan",
            "发起巡检",
            "按知识库已有巡检授权启动真实后台检查；返回等待句柄，不能视为完成或变更配置",
            {},
        ),
        (
            "observe_maintenance_scan",
            "观察巡检进展",
            "读取后台巡检覆盖、未完成原因及当前版本匹配；进行中返回等待",
            {
                "run_id": identifier,
                "page": {"type": "integer", "minimum": 1},
                "issue_id": identifier,
            },
        ),
        (
            "follow_maintenance_issue",
            "跟进维护问题",
            "经确认将当前问题标为处理中，不修改原文、不关闭问题",
            {"issue_id": identifier},
        ),
        (
            "request_maintenance_recheck",
            "请求问题复检",
            "经确认复检当前资料；沿用现有问题，只有真实复检通过才能关闭",
            {"issue_id": identifier},
        ),
        (
            "notify_maintenance_issue",
            "提醒维护人",
            "经确认把问题加入现有维护人摘要通知，同日自动合并去重",
            {"issue_id": identifier},
        ),
        (
            "prepare_maintenance_report",
            "整理维护报告",
            "生成所选问题的脱敏处理建议草稿；不修改知识库。用整理文档工具保存可预览成果",
            {
                "issue_ids": {"type": "array", "items": identifier, "minItems": 1, "maxItems": 25},
            },
        ),
    ]
    return [
        {
            "key": key,
            "label": label,
            "description": description,
            "mutating": key in MUTATIONS,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": [
                    k
                    for k in properties
                    if k in {"issue_id", "issue_ids", "run_id", "asset_id"}
                    and not (key == "observe_maintenance_scan" and k == "issue_id")
                ],
                "additionalProperties": False,
            },
        }
        for key, label, description, properties in specs
    ]


async def _live(session, caller):
    if not caller:
        raise access.reject(403)
    refreshed = await access.actor_context(session, caller.user_id, caller.active_company_role)
    if not refreshed or not refreshed.is_business_user:
        raise access.reject(403)
    return refreshed


def _uuid(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise access.reject(422, "工具参数无效") from None


def _page(command):
    value = command.get("page", 1)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100000:
        raise access.reject(422, "页码无效")
    return value


def _result(observation, *, sources=(), waiting=None, confirmation=None):
    if confirmation:
        receipt = "等待你确认具体动作；尚未执行。"
    elif observation.get("receipt_summary"):
        receipt = observation["receipt_summary"]
    elif observation.get("message"):
        receipt = observation["message"]
    elif observation.get("issue_id"):
        receipt = f"已核对问题：{observation.get('problem', '维护问题')}；当前状态：{observation.get('status', '待核对')}。"
    elif observation.get("source_modified") is False:
        receipt = "已整理所选问题的脱敏修订建议；尚未修改知识资产。"
    elif "active_issues" in observation:
        receipt = f"已盘点当前知识库，可巡检 {observation['scope']['target_count']} 份资料，有 {observation['active_issues']} 个未结束问题。"
    else:
        receipt = f"已读取本页 {len(observation.get('items', []))} 个问题；列表仅包含当前身份可维护的资料。"
    observation = {**observation, "receipt_summary": receipt}
    return {
        "observation": redact_personal_data(observation),
        "sources": list(sources),
        "artifacts": [],
        "waiting": waiting,
        "confirmation": confirmation,
    }


def _library_ref(key):
    return {"kind": "maintenance", "source_type": "library", "context_key": key}


def _waiting(key, run, *, issue_id=None):
    if run.status not in ACTIVE_RUNS:
        return None
    return {
        "action": "observe_maintenance_scan",
        "arguments": {
            "library_key": key,
            "run_id": str(run.id),
            **({"issue_id": str(issue_id)} if issue_id else {}),
        },
        "retry_after_seconds": 10,
    }


def _run_observation(run):
    return {
        "run_id": str(run.id),
        "status": run.status,
        "target_count": run.target_count,
        "completed_count": run.completed_count,
        "incomplete_count": run.incomplete_count,
        "skipped_count": run.skipped_count,
        "reasons": run.reasons,
        "finished": run.status not in ACTIVE_RUNS,
        "coverage_complete": run.status == "completed",
        "message": "巡检仍在后台执行，当前结果不是最终结论。"
        if run.status in ACTIVE_RUNS
        else "巡检已结束，请结合覆盖情况及未完成原因判断；运行结束不代表所有问题已解决。",
    }


def _evidence_metadata(value):
    """Only structured check facts cross the model boundary, never raw quotations.

    Even historical findings may contain unredacted content. Whitelisting numeric
    locations and known detector codes also excludes names not caught by patterns.
    """
    allowed_categories = {
        "phone",
        "email",
        "id_card",
        "bank_card",
        "address",
        "name",
        "personal_name",
        "mobile",
        "passport",
        "account",
        "identity",
        "contact",
        "personal_information",
    }
    result = {}
    if value.get("basis") in {
        "local_personal_information_check",
        "sha256_equal",
        "title_similarity",
    }:
        result["basis"] = value["basis"]
    for key in ("total", "similarity", "start", "end"):
        if isinstance(value.get(key), (int, float)) and not isinstance(value[key], bool):
            result[key] = value[key]
    if isinstance(value.get("counts"), dict):
        result["counts"] = {
            k: v
            for k, v in value["counts"].items()
            if k in allowed_categories and isinstance(v, int) and v >= 0
        }
    locations = []
    for item in value.get("locations", [])[:20]:
        if not isinstance(item, dict):
            continue
        location = {
            k: item[k] for k in ("start", "end") if isinstance(item.get(k), int) and item[k] >= 0
        }
        if item.get("source") in {"body", "summary", "title", "tag"}:
            location["source"] = item["source"]
        if item.get("category") in allowed_categories:
            location["category"] = item["category"]
        if location:
            locations.append(location)
    if locations:
        result["locations"] = locations
        result["locations_truncated"] = bool(value.get("locations_truncated"))
    result["raw_values_included"] = False
    return result


def _recommendation(rule):
    if rule == "personal_information":
        return "由有权维护人按证据位置检查个人信息，清理或脱敏正文和摘要后提交复检；报告与通知只保留类型、数量和位置。"
    if rule in {"exact_duplicate", "possible_duplicate", "possible_version"}:
        return "核对关联资料与当前有效版本，确认版本关系或重复关系后按既有流程处理，再复检。"
    if rule in {"file_unavailable", "parse_failed", "index_failed"}:
        return "核对文件及解析、索引状态；由有权人员修复对应异常后复检，尚不可据此判断内容质量。"
    if rule in SUGGESTIONS:
        return "由维护人补充对应资料信息后复检；这是一项完善建议，不应据此认定资料不可用。"
    return "由有原文权限的维护人核对当前版本与证据，修订资料后请求复检；疑似判断需人工核实。"


async def _issue(session, caller, key, issue_id, *, lock=False):
    canonical = await maintenance._canonical_id(session, _uuid(issue_id))
    query = maintenance.issue_query(caller).where(
        MaintenanceIssue.id == canonical, MaintenancePolicy.library_key == key
    )
    row = (await session.execute(query.execution_options(populate_existing=True))).first()
    if not row:
        raise access.reject()
    issue, asset, policy = row
    if lock:
        await session.scalar(
            select(MaintenancePolicy)
            .where(MaintenancePolicy.id == policy.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        await session.scalar(
            select(KnowledgeAsset)
            .where(KnowledgeAsset.id == asset.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        await session.scalar(
            select(MaintenanceIssue)
            .where(MaintenanceIssue.id == issue.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        # Reevaluate assignments under the same locks used by the existing writer.
        row = (await session.execute(query.execution_options(populate_existing=True))).first()
        if not row:
            raise access.reject()
        issue, asset, policy = row
    matches = issue.version_id == asset.current_version_id
    original_authority = await access.original_allowed(session, caller, asset, agent=True)
    allowed = matches and original_authority
    related_authority, related_version = None, None
    if issue.related_asset_id:
        other = await session.get(KnowledgeAsset, issue.related_asset_id, populate_existing=True)
        related_authority = bool(
            other and await access.original_allowed(session, caller, other, agent=True)
        )
        related_version = str(other.current_version_id) if other else None
        allowed = (
            allowed
            and other is not None
            and issue.evidence.get("related_version_id") == str(other.current_version_id)
            and related_authority
        )
    # No full source text, human names, free-text notes or quotes are passed through.
    projection = {
        "issue_id": str(issue.id),
        "asset_id": str(asset.id),
        "version_id": str(asset.current_version_id) if asset.current_version_id else None,
        "library_key": key,
        "title": redact_personal_information(asset.title),
        "rule": issue.rule,
        "problem": RULES.get(issue.rule, ("", "维护问题"))[1],
        "category": issue.category,
        "status": issue.status,
        "issue_status": issue.status,
        "suspected": issue.suspected,
        "requires_recheck": issue.requires_recheck,
        "current_version_matches": matches,
        "evidence_available": allowed,
        "evidence": _evidence_metadata(issue.evidence) if allowed else {},
        "updated_at": access.stamp(issue.updated_at).isoformat(),
        "can_act": knowledge_maintainer_allowed(caller, asset),
        "recommendation": _recommendation(issue.rule),
        "url": f"/ai-workspace/agents/knowledge-maintenance?library={key}&tab=issues&asset_id={asset.id}&status=all",
    }
    latest_action = await session.scalar(
        select(MaintenanceIssueEvent.action)
        .where(MaintenanceIssueEvent.issue_id == issue.id)
        .order_by(MaintenanceIssueEvent.created_at.desc(), MaintenanceIssueEvent.id.desc())
        .limit(1)
    )
    projection["recheck_passed"] = bool(
        issue.status == "resolved" and matches and latest_action == "recheck_passed"
    )
    ref = {
        "kind": "maintenance",
        "source_type": "issue",
        "context_key": key,
        "issue_id": str(issue.id),
        "asset_id": str(asset.id),
        "version_id": projection["version_id"],
        "projection_digest": digest(
            {
                "title": projection["title"],
                "original_authority": original_authority,
                "related_authority": related_authority,
                "related_version": related_version,
            }
        ),
    }
    return issue, asset, policy, projection, ref


async def sources_available(session, caller, refs):
    """Withhold prior outputs after loss of authority, replacement or withdrawn evidence."""
    try:
        caller = await _live(session, caller)
        for ref in refs:
            if ref.get("kind") != "maintenance":
                return False
            key = ref["context_key"]
            await workspace_tools.check_context(session, caller, key)
            if ref["source_type"] == "library":
                await maintenance._library(session, caller, key)
            elif ref["source_type"] == "issue":
                *_, current = await _issue(session, caller, key, ref["issue_id"])
                if current != ref:
                    return False
            elif ref["source_type"] == "knowledge_asset":
                _, current = await _knowledge_evidence(session, caller, key, ref["asset_id"])
                if current != ref:
                    return False
            elif ref["source_type"] == "asset_metadata":
                if await _asset_metadata_ref(session, caller, key, ref["asset_id"]) != ref:
                    return False
            else:
                return False
        return True
    except (KeyError, ValueError, TypeError, HTTPException):
        return False


async def _asset_metadata_ref(session, caller, key, asset_id):
    project_id = access.parse_key(key)
    asset = await session.scalar(
        select(KnowledgeAsset)
        .where(
            KnowledgeAsset.id == _uuid(asset_id),
            KnowledgeAsset.scope == ("project" if project_id else "company"),
            KnowledgeAsset.project_id == project_id,
            KnowledgeAsset.deleted_at.is_(None),
            KnowledgeAsset.asset_status != "deleted",
            access.manager_filter(caller, include_inactive=True),
        )
        .execution_options(populate_existing=True)
    )
    if asset is None:
        raise access.reject()
    return {
        "kind": "maintenance",
        "source_type": "asset_metadata",
        "context_key": key,
        "asset_id": str(asset.id),
        "version_id": str(asset.current_version_id) if asset.current_version_id else None,
        "projection_digest": digest(redact_personal_information(asset.title)),
    }


async def _knowledge_evidence(session, caller, key, asset_id):
    await workspace_tools.check_context(session, caller, key)
    checked = await knowledge_workspace_tools.inspect(session, caller, key, _uuid(asset_id))
    if not checked:
        raise access.reject()
    detail, current, _ = checked
    availability, evidence = await knowledge_workspace_tools.evidence(
        session, caller, key, {"asset_id": str(detail.id), "version_id": current["version_id"]}, ""
    )
    if evidence is None:
        raise access.reject(409, "资料版本已变化，请重新核对")
    projection = redact_personal_data(evidence.model_dump(mode="json"))
    projection["availability"] = availability
    projection["human_original_access"] = projection.pop("original")
    projection["receipt_summary"] = (
        "已核对当前可见版本及已采纳的版本关系；摘要差异不代表完整原文差异。"
    )
    ref = {
        "kind": "maintenance",
        "source_type": "knowledge_asset",
        "context_key": key,
        "asset_id": str(detail.id),
        "version_id": current["version_id"],
        "projection_digest": digest(
            {
                field: projection[field]
                for field in (
                    "title",
                    "summary",
                    "version",
                    "previous_summary",
                    "current_summary",
                    "compared_version",
                    "old_source_links",
                    "human_original_access",
                )
            }
        ),
    }
    return projection, ref


async def execute(session, caller, context_key, command, *, request_id, confirmed=False):
    """Execute one registered step; confirmation is trusted runtime state, not input JSON."""
    caller = await _live(session, caller)
    if not isinstance(command, dict):
        raise access.reject(422, "工具参数无效")
    key = context_key
    access.parse_key(key)
    await workspace_tools.check_context(session, caller, key)
    if command.get("library_key", key) != key:
        raise access.reject(403, "工具只能操作当前会话选择的知识库")
    action = command.get("action")
    if action not in {item["key"] for item in definitions()}:
        raise access.reject(422, "不支持此维护工具")
    trace_id = "workspace-maintenance:" + str(_uuid(request_id))
    if action == "inspect_knowledge_asset":
        projected, ref = await _knowledge_evidence(session, caller, key, command.get("asset_id"))
        return _result(projected, sources=[ref])
    if action == "maintenance_overview":
        policy = await maintenance._library(session, caller, key)
        scope = await assess_scope(session, caller, access.parse_key(key))
        issues = await maintenance.list_issues(session, caller, key=key)
        recent = await maintenance.runs(session, caller, key)
        return _result(
            {
                "library_key": key,
                "scope": scope.model_dump(mode="json"),
                "configured": policy is not None,
                "content_authorized": bool(policy and policy.content_authorized),
                "automatic_inspection": bool(policy and policy.enabled),
                "active_issues": issues.total,
                "issue_counts": issues.counts,
                "latest_run": _run_observation(recent[0]) if recent else None,
            },
            sources=[_library_ref(key)],
        )
    if action == "list_maintenance_issues":
        status, category = command.get("status", "active"), command.get("category")
        if status not in ISSUE_STATUSES or category is not None and category not in CATEGORIES:
            raise access.reject(422, "筛选条件无效")
        found = await maintenance.list_issues(
            session, caller, key=key, status=status, category=category, page=_page(command)
        )
        items, refs = [], []
        for item in found.items:
            *_, projected, ref = await _issue(session, caller, key, item.id)
            items.append(projected)
            refs.append(ref)
        return _result(
            {
                "items": items,
                "total": found.total,
                "page": found.page,
                "page_size": found.page_size,
                "has_more": found.page * found.page_size < found.total,
                "scope": "仅当前身份可维护的资料，不代表知识库全部问题",
            },
            sources=refs,
        )
    if action == "inspect_maintenance_issue":
        *_, projected, ref = await _issue(session, caller, key, command.get("issue_id"))
        return _result(projected, sources=[ref])
    if action == "observe_maintenance_scan":
        refs = [_library_ref(key)]
        if command.get("issue_id"):
            issue, asset, policy, _, ref = await _issue(session, caller, key, command["issue_id"])
            run = await session.get(
                MaintenanceRun, _uuid(command.get("run_id")), populate_existing=True
            )
            if not run or run.policy_id != policy.id or run.target_asset_id != asset.id:
                raise access.reject()
            report = await project_detail(session, caller, policy, run, page=_page(command))
            refs = [ref]
        else:
            report = await maintenance.run_detail(
                session, caller, key, _uuid(command.get("run_id")), page=_page(command)
            )
        items = [item.model_dump(mode="json") for item in report.items]
        refs.extend(
            [
                await _asset_metadata_ref(session, caller, key, item.asset_id)
                for item in report.items
            ]
        )
        return _result(
            {
                **_run_observation(report),
                "items": items,
                "page": report.page,
                "total": report.total,
                "has_more": report.page * report.page_size < report.total,
                "scope": report.current_scope.model_dump(mode="json"),
            },
            sources=refs,
            waiting=_waiting(key, report, issue_id=command.get("issue_id")),
        )
    if action == "prepare_maintenance_report":
        ids = command.get("issue_ids")
        if not isinstance(ids, list) or not 1 <= len(ids) <= 25:
            raise access.reject(422, "请明确选择 1 至 25 个问题")
        items, refs = [], []
        for issue_id in dict.fromkeys(str(_uuid(value)) for value in ids):
            *_, projected, ref = await _issue(session, caller, key, issue_id)
            items.append(projected)
            refs.append(ref)
        lines = ["# 知识维护建议", "", "以下仅为所选问题的脱敏建议，尚未修改任何知识资产。", ""]
        for item in items:
            lines.extend(
                [
                    f"## {item['title']}",
                    f"问题：{item['problem']}",
                    f"当前状态：{item['status']}；当前版本证据：{'可用' if item['evidence_available'] else '需重新核对'}",
                    item["recommendation"],
                    "",
                ]
            )
        return _result(
            {
                "title": "知识维护建议",
                "content": "\n".join(lines),
                "items": items,
                "source_modified": False,
                "saved": False,
            },
            sources=refs,
        )
    if action == "start_maintenance_scan":
        policy = await maintenance._library(session, caller, key, lock=True)
        # A role can be revoked while this action waits for another scan's policy
        # lock. Rebuild authority after acquiring it, not only before the wait.
        caller = await _live(session, caller)
        await maintenance._library(session, caller, key)
        if not policy:
            raise access.reject(409, "请先保存巡检配置")
        if "policy_revision" in command and command["policy_revision"] != policy.revision:
            raise access.reject(409, "巡检配置已变化，请重新确认")
        run = await maintenance.run_now(session, caller, key, trace_id, commit=False)
        return _result(
            _run_observation(run), sources=[_library_ref(key)], waiting=_waiting(key, run)
        )
    issue, asset, policy, projected, ref = await _issue(
        session, caller, key, command.get("issue_id"), lock=True
    )
    caller = await _live(session, caller)
    issue, asset, policy, projected, ref = await _issue(session, caller, key, issue.id)
    if not projected["can_act"]:
        raise access.reject()
    if issue.status not in ACTIVE:
        raise access.reject(409, "此问题当前不处于待跟进状态，请重新核对")
    owners = await access.recipients(session, asset) if action == "notify_maintenance_issue" else []
    recipients_signature = digest(sorted(owner["id"] for owner in owners))
    if action == "notify_maintenance_issue" and not owners:
        raise access.reject(409, "没有当前有效维护人，请先配置维护责任")
    if not confirmed:
        labels = {
            "follow_maintenance_issue": "标记为处理中",
            "request_maintenance_recheck": "对当前版本发起复检，复检通过后才会关闭问题",
            "notify_maintenance_issue": f"加入 {len(owners)} 位当前维护人的摘要提醒，按现有发送时间合并通知",
        }
        return _result(
            projected,
            sources=[ref],
            confirmation={
                "summary": f"将《{projected['title']}》的“{projected['problem']}”{labels[action]}。",
                "arguments": {
                    "action": action,
                    "library_key": key,
                    "issue_id": str(issue.id),
                    "expected_updated_at": projected["updated_at"],
                    "expected_version_id": projected["version_id"],
                    "policy_revision": policy.revision,
                    **({"recipients_signature": recipients_signature} if owners else {}),
                },
            },
        )
    if (
        command.get("expected_updated_at") != projected["updated_at"]
        or command.get("expected_version_id") != projected["version_id"]
        or command.get("policy_revision") != policy.revision
    ):
        raise access.reject(409, "问题、版本或巡检配置已变化，请重新核对并确认")
    if action == "notify_maintenance_issue":
        if command.get("recipients_signature") != recipients_signature:
            raise access.reject(409, "维护责任已变化，请重新确认提醒对象")
        now = utc_now()
        for owner in owners:
            await _digest(session, issue, _uuid(owner["id"]), ScanSettings(**policy.settings), now)
        await audit.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action="maintenance.reminder_requested",
            trace_id=trace_id,
            target_type="maintenance_issue",
            target_id=issue.id,
            extra={"recipient_count": len(owners)},
        )
        await session.flush()
        return _result(
            {
                "issue_id": str(issue.id),
                "recipient_count": len(owners),
                "notification_status": "merged_into_daily_digest",
                "message": "已加入维护人摘要提醒；同日提醒合并，通知送达由既有发送任务处理。",
            },
            sources=[ref],
        )
    command_action = "recheck" if action == "request_maintenance_recheck" else "in_progress"
    if issue.status != "in_progress" or command_action == "recheck":
        await maintenance.transition(
            session,
            caller,
            issue.id,
            IssueCommand(
                expected_updated_at=issue.updated_at,
                action=command_action,
                reason="通过知识维护 Agent 请求",
            ),
            trace_id,
            commit=False,
        )
    *_, projected, ref = await _issue(session, caller, key, issue.id)
    waiting = None
    if command_action == "recheck":
        run = await session.scalar(
            select(MaintenanceRun)
            .where(
                MaintenanceRun.policy_id == policy.id,
                MaintenanceRun.target_asset_id == asset.id,
                MaintenanceRun.status.in_(ACTIVE_RUNS),
            )
            .order_by(MaintenanceRun.started_at.desc())
            .limit(1)
        )
        if run:
            projected["run"] = _run_observation(run)
            waiting = _waiting(key, run, issue_id=issue.id)
            projected["message"] = "复检已排队，等待当前版本检查结果；尚未通过复检，问题继续跟踪。"
    return _result(projected, sources=[ref], waiting=waiting)

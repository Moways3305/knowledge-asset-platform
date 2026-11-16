"""Commands and permission-filtered projections for the first prebuilt agent."""

import uuid
from datetime import timedelta

from sqlalchemy import func, select

from app.db.utils import utc_now
from app.models.identity import Project
from app.models.knowledge import KnowledgeAsset
from app.models.maintenance_agent import (
    MaintenanceIssue,
    MaintenanceIssueEvent,
    MaintenancePolicy,
    MaintenanceRun,
)
from app.schemas.enums import AuditLogType
from app.schemas.maintenance_agent import (
    IssueDetail,
    IssueOut,
    IssuePage,
    PolicyOut,
    RunOut,
    ScanSettings,
)
from app.services import audit
from app.services import maintenance_access as access
from app.services.generation_models import safe_generation_model_options
from app.services.maintenance_jobs import ACTIVE, start_run
from app.services.maintenance_reports import project_detail
from app.services.permission import knowledge_manager_allowed


async def policies(session, caller):
    if not caller.is_active or not caller.is_business_user:
        raise access.reject(403)
    libraries = [("company", "公司知识库", None)]
    projects = (
        await session.scalars(
            select(Project)
            .where(Project.id.in_(caller.active_project_ids), Project.status != "archived")
            .order_by(Project.name)
        )
    ).all()
    libraries.extend((f"project:{p.id}", p.name, p.id) for p in projects)
    stored = {
        p.library_key: p
        for p in (
            await session.scalars(
                select(MaintenancePolicy).where(
                    MaintenancePolicy.library_key.in_([key for key, _, _ in libraries])
                )
            )
        ).all()
    }
    return [
        PolicyOut(
            id=stored[key].id if key in stored else None,
            library_key=key,
            name=name,
            enabled=stored[key].enabled if key in stored else False,
            content_authorized=stored[key].content_authorized if key in stored else False,
            revision=stored[key].revision if key in stored else 0,
            settings=ScanSettings(**stored[key].settings) if key in stored else ScanSettings(),
            last_error=stored[key].last_error if key in stored else None,
            can_configure=access.library_allowed(caller, project_id),
        )
        for key, name, project_id in libraries
    ]


async def _library(session, caller, key, *, lock=False):
    project_id = access.parse_key(key)
    if not access.library_allowed(caller, project_id):
        raise access.reject()
    if project_id:
        project = await session.get(Project, project_id)
        if not project or project.status == "archived":
            raise access.reject()
    query = select(MaintenancePolicy).where(MaintenancePolicy.library_key == key)
    return await session.scalar(query.with_for_update() if lock else query)


async def configure(session, caller, key, command, trace_id):
    policy = await _library(session, caller, key, lock=True)
    if (policy.revision if policy else 0) != command.expected_revision:
        raise access.reject(409, "配置已更新，请刷新后重试")
    # Bound each free-text rule as well as the list. It remains untrusted model data.
    settings = command.settings
    if settings.model_ref != "system_default" and settings.model_ref not in {
        item["model_ref"] for item in await safe_generation_model_options(session)
    }:
        raise access.reject(422, "所选分析模型已停用或不可用，请重新选择模型")
    if any(
        not v.strip() or len(v) > 100
        for v in [*settings.required_tags, *settings.required_sections]
    ):
        raise access.reject(422, "标签和必要章节须为 1—100 字")
    if not policy:
        if session.bind.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        await session.execute(
            insert(MaintenancePolicy)
            .values(
                id=uuid.uuid4(),
                library_key=key,
                project_id=access.parse_key(key),
                revision=0,
                authorized_by=caller.user_id,
                authorized_role=next(iter(caller.active_company_roles)),
            )
            .on_conflict_do_nothing(index_elements=["library_key"])
        )
        policy = await _library(session, caller, key, lock=True)
        if policy.revision != command.expected_revision:
            raise access.reject(409, "配置已更新，请刷新后重试")
    policy.enabled, policy.content_authorized = command.enabled, command.content_authorized
    policy.authorized_by, policy.authorized_role = (
        caller.user_id,
        next(iter(caller.active_company_roles)),
    )
    policy.settings, policy.updated_at, policy.last_error = settings.model_dump(), utc_now(), None
    policy.revision += 1
    await session.flush()
    runs = (
        await session.scalars(
            select(MaintenanceRun)
            .where(
                MaintenanceRun.policy_id == policy.id,
                MaintenanceRun.status.in_(["queued", "running"]),
            )
            .with_for_update()
        )
    ).all()
    for run in runs:
        run.status, run.finished_at, run.claim_token = "cancelled", utc_now(), None
        run.reasons = {**run.reasons, "policy_changed": 1}
    await audit.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action="maintenance.policy_changed",
        trace_id=trace_id,
        target_type="maintenance_policy",
        target_id=policy.id,
        project_id=policy.project_id,
        extra={
            "revision": policy.revision,
            "enabled": policy.enabled,
            "content_authorized": policy.content_authorized,
        },
    )
    await session.commit()
    return next(p for p in await policies(session, caller) if p.library_key == key)


async def run_now(session, caller, key, trace_id):
    policy = await _library(session, caller, key, lock=True)
    if not policy:
        raise access.reject(409, "请先保存巡检配置")
    if not caller.can_discover_l5 and policy.authorized_role in {"boss", "consulting_director"}:
        raise access.reject(409, "请先以当前身份重新保存巡检配置")
    run = await start_run(session, policy)
    if not run:
        await session.commit()
        raise access.reject(409, "巡检授权已失效，请重新保存配置授权")
    await audit.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action="maintenance.run_requested",
        trace_id=trace_id,
        target_type="maintenance_run",
        target_id=run.id,
    )
    await session.commit()
    return RunOut.model_validate(run, from_attributes=True)


async def runs(session, caller, key, page=1):
    policy = await _library(session, caller, key)
    if not policy:
        return []
    query = select(MaintenanceRun).where(MaintenanceRun.policy_id == policy.id)
    if not caller.can_discover_l5:
        query = query.where(MaintenanceRun.includes_l5.is_(False))
    rows = (
        await session.scalars(
            query.order_by(MaintenanceRun.started_at.desc()).offset((page - 1) * 25).limit(25)
        )
    ).all()
    return [RunOut.model_validate(r, from_attributes=True) for r in rows]


async def run_detail(session, caller, key, run_id, *, page=1, status=None):
    policy = await _library(session, caller, key)
    if not policy:
        raise access.reject()
    run = await session.get(MaintenanceRun, run_id)
    if not run or run.policy_id != policy.id or (run.includes_l5 and not caller.can_discover_l5):
        raise access.reject()
    return await project_detail(session, caller, policy, run, page=page, status=status)


def issue_query(caller):
    return access.visible_issue_query(caller).add_columns(KnowledgeAsset, MaintenancePolicy)


async def _project(session, caller, issue, asset, policy):
    owners = await access.recipients(session, asset)
    return IssueOut(
        id=issue.id,
        asset_id=asset.id,
        title=asset.title,
        library_key=policy.library_key,
        rule=issue.rule,
        category=issue.category,
        status=issue.status,
        suspected=issue.suspected,
        first_seen_at=issue.first_seen_at,
        last_seen_at=issue.last_seen_at,
        updated_at=issue.updated_at,
        snooze_until=issue.snooze_until,
        responsible=owners,
        can_act=knowledge_manager_allowed(caller, asset),
    )


async def list_issues(
    session, caller, *, key=None, status="active", category=None, mine=False, page=1
):
    query = issue_query(caller)
    if key:
        query = query.where(MaintenancePolicy.library_key == key)
    if status == "active":
        query = query.where(MaintenanceIssue.status.in_(ACTIVE))
    elif status != "all":
        query = query.where(MaintenanceIssue.status == status)
    if category:
        query = query.where(MaintenanceIssue.category == category)
    # Assignment validity is a live projection; filter before pagination/count.
    if mine:
        query = query.where(access.responsibility_filter(caller))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await session.execute(
            query.order_by(MaintenanceIssue.last_seen_at.desc(), MaintenanceIssue.id)
            .offset((page - 1) * 25)
            .limit(25)
        )
    ).all()
    return IssuePage(
        items=[await _project(session, caller, *row) for row in rows],
        total=total,
        page=page,
        page_size=25,
    )


async def detail(session, caller, issue_id, trace_id=None):
    row = (
        await session.execute(issue_query(caller).where(MaintenanceIssue.id == issue_id))
    ).first()
    if not row:
        raise access.reject()
    issue, asset, policy = row
    allowed = issue.version_id == asset.current_version_id and await access.original_allowed(
        session, caller, asset
    )
    if issue.related_asset_id:
        other = await session.get(KnowledgeAsset, issue.related_asset_id)
        allowed = (
            allowed
            and issue.evidence.get("related_version_id") == str(other.current_version_id)
            and await access.original_allowed(session, caller, other)
        )
    evidence = dict(issue.evidence) if allowed else {}
    if allowed and issue.related_asset_id:
        evidence["related_asset_id"] = str(issue.related_asset_id)
        evidence["related_title"] = other.title
    history = (
        await session.scalars(
            select(MaintenanceIssueEvent)
            .where(MaintenanceIssueEvent.issue_id == issue.id)
            .order_by(MaintenanceIssueEvent.created_at.desc())
            .limit(50)
        )
    ).all()
    if allowed and issue.evidence.get("quote"):
        await audit.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action="maintenance.evidence_viewed",
            trace_id=trace_id,
            target_type="knowledge_asset",
            target_id=asset.id,
            project_id=asset.project_id,
            risk_level="high" if asset.confidentiality_level == "L5" else None,
            extra={"issue_id": str(issue.id)},
        )
        await session.commit()
    return IssueDetail(
        **(await _project(session, caller, issue, asset, policy)).model_dump(),
        evidence=evidence,
        evidence_available=allowed,
        current_version_matches=issue.version_id == asset.current_version_id,
        history=[
            {
                "action": h.action,
                "reason": h.reason if allowed else "",
                "created_at": h.created_at.isoformat(),
            }
            for h in history
        ],
    )


async def transition(session, caller, issue_id, command, trace_id):
    # Same lock order as scan finalization: run/policy commands are serialized by policy.
    visible = (
        await session.execute(issue_query(caller).where(MaintenanceIssue.id == issue_id))
    ).first()
    if not visible:
        raise access.reject()
    _, asset, policy = visible
    policy = await session.scalar(
        select(MaintenancePolicy)
        .where(MaintenancePolicy.id == policy.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    asset = await session.scalar(
        select(KnowledgeAsset)
        .where(KnowledgeAsset.id == asset.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        not access.eligible(asset)
        or not (
            await session.execute(issue_query(caller).where(MaintenanceIssue.id == issue_id))
        ).first()
    ):
        raise access.reject()
    issue = await session.scalar(
        select(MaintenanceIssue)
        .where(MaintenanceIssue.id == issue_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if access.stamp(issue.updated_at) != access.stamp(command.expected_updated_at):
        raise access.reject(409, "问题已更新，请刷新后再处理")
    if not knowledge_manager_allowed(caller, asset):
        raise access.reject()
    action, now = command.action, utc_now()
    if action in {"snoozed", "false_positive", "resolved"} and not command.reason.strip():
        raise access.reject(422, "请填写处理原因")
    if action == "resolved" and not issue.suspected:
        raise access.reject(409, "客观问题需要修正资产后重新检查")
    if action in {"resolved", "false_positive"} and not await access.original_allowed(
        session, caller, asset
    ):
        raise access.reject(403, "确认判断需要原文权限")
    if action in {"resolved", "false_positive"}:
        if issue.version_id != asset.current_version_id:
            raise access.reject(409, "资产版本已变化，请重新检查")
        if issue.related_asset_id:
            other = await session.get(KnowledgeAsset, issue.related_asset_id)
            if not await access.original_allowed(session, caller, other):
                raise access.reject(403, "确认判断需要关联资料的原文权限")
            if issue.evidence.get("related_version_id") != str(other.current_version_id):
                raise access.reject(409, "关联资料版本已变化，请重新检查")
    if issue.status in {"resolved", "not_applicable", "false_positive"} and action != "recheck":
        raise access.reject(409, "此问题已结束，可重新检查")
    if action == "snoozed" and (
        not command.snooze_until
        or not now < access.stamp(command.snooze_until) <= now + timedelta(days=365)
    ):
        raise access.reject(422, "暂缓日期必须在未来一年内")
    if action == "recheck":
        run = await start_run(session, policy, kind="recheck", asset_id=asset.id)
        if not run:
            raise access.reject(409, "巡检授权已失效，请重新保存配置")
        action = "awaiting_recheck"
    issue.status, issue.updated_at = action, now
    issue.snooze_until = command.snooze_until if action == "snoozed" else None
    session.add(
        MaintenanceIssueEvent(
            issue_id=issue.id, actor_id=caller.user_id, action=action, reason=command.reason.strip()
        )
    )
    await audit.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action="maintenance.issue_changed",
        trace_id=trace_id,
        target_type="maintenance_issue",
        target_id=issue.id,
        extra={"status": action},
    )
    await session.commit()
    return await detail(session, caller, issue.id, trace_id)

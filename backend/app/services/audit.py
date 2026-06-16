"""集中审计写入服务。

**所有模块写审计只能经本模块唯一入口 `record_event`**，不得各自散写。
本模块负责：角色快照、写入时脱敏、severity / risk_level 标记。

事务边界：`record_event` 只把事件 add 进调用方的 session（不 commit），由触发它的
业务写动作在同一事务里一起 commit——业务回滚则审计同回滚，保证原子且不漏记。
被拒动作在 raise 前需先 `record_event` 再显式 commit（用 `record_denied` 辅助）。

不可变：本模块只提供写入与「标记处理」，不提供修改 / 删除原始审计事实的能力。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditEvent
from app.models.identity import ProjectMember, User
from app.schemas.audit import (
    AuditEventOut,
    AuditListResponse,
    AuditTraceResponse,
    MarkProcessedResponse,
)
from app.schemas.enums import (
    AlertSeverity,
    AuditAction,
    AuditLogType,
    CompanyRole,
    ConfidentialityLevel,
    MemberStatus,
)
from app.schemas.permission import CallerContext

# 公司角色快照的治理优先级（多角色时取治理代表角色；全集另存 extra.actor_company_roles）。
_COMPANY_ROLE_PRIORITY = [
    CompanyRole.boss.value,
    CompanyRole.consulting_director.value,
    CompanyRole.consultant.value,
    CompanyRole.admin.value,
]

# 写入时脱敏：snapshot / extra 中绝不允许出现的键（防御性二次过滤）。
# 业务侧本就只应传安全元数据；这里再兜底剔除技术敏感标识与原文载体。
_FORBIDDEN_KEYS = {
    "storage_ref",
    "source_file_ref",
    "vector_id",
    "api_key",
    "dataset_id",
    "workflow_id",
    "kb_id",
    "bucket",
    "collection",
    "object_key",
    "download_url",
    "file_url",
    "preview_token",
    "token",
    "token_hash",
    "preview_entry_url",
    "content_text",
    "content",
    "file_content",
    "raw_text",
    # WeKnora 底座内部标识：一律视同 storage_ref，绝不入审计。
    "weknora_kb_id",
    "weknora_doc_id",
    "weknora_chunk_id",
    "weknora_api_key",
    "knowledge_id",
    "file_path",
    "llm_api_key",
    "authorization",
    # server-only chunk 引用：视同 storage_ref，绝不入审计（防御性二次过滤）。
    "target_weknora_chunk_ref",
    "cited_weknora_chunk_ref",
    "weknora_chunk_ref",
    # 企微 OAuth / 微盘：token / 授权码 / secret / 临时下载 URL / file_id 绝不入审计。
    "wecom_access_token",
    "access_token",
    "auth_code",
    "oauth_code",
    "oauth_state",
    "wecom_app_secret",
    "wecom_secret",
    "wecom_file_id",
}

# 值级脱敏占位符与敏感标记。即便键名无害，字符串值若是对象存储 / 文件 / 内部地址
# 或明显的内部存储用语，也整串替换为占位符，避免敏感载体经无害键名落库。
# 仅整串替换；UUID / trace_id / asset_id / 枚举值 / denied_reason / access layer /
# 角色 key 等安全标识不含这些标记，不受影响。
_VALUE_REDACTED = "[redacted]"
_FORBIDDEN_VALUE_MARKERS = (
    "s3://",
    "oss://",
    "file://",
    "http://",
    "https://",
    "internal://",
    "object storage",
    "bucket",
    "sk-",  # WeKnora / 外部 API key 前缀，命中整串脱敏
    "bearer ",  # Authorization: Bearer <key>，命中整串脱敏
    "wk-doc",  # WeKnora doc 引用形态（如 wk-doc-...#0），命中整串脱敏
    "wk-kb",  # WeKnora KB 引用形态，命中整串脱敏
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sanitize_value(value: str) -> str:
    """字符串值级脱敏：命中对象存储 / 文件 URL / 内部地址等标记则整串替换为占位符。"""
    lowered = value.lower()
    if any(marker in lowered for marker in _FORBIDDEN_VALUE_MARKERS):
        return _VALUE_REDACTED
    return value


def sanitize_text(value: str | None) -> str | None:
    """公共字符串值级脱敏入口（供生命周期 reason / 通知 title·content 等用户文本复用）。

    与审计写入时的值级脱敏同一口径，避免各模块重复维护标记表：命中对象存储 /
    文件 URL / 内部地址 / `bucket` / `object storage` 等敏感标记的整串替换为
    `[redacted]`；None 原样返回。安全文案（如「项目结束归档」「复核通过」）、枚举值、
    UUID / trace_id / access layer 等不含这些标记，不受影响。
    """
    if value is None:
        return None
    return _sanitize_value(value)


def _sanitize(value):
    """递归脱敏快照 / extra：剔除禁止键 + 对字符串值做值级脱敏（写入时兜底防线）。"""
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items() if str(k).lower() not in _FORBIDDEN_KEYS}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    if isinstance(value, str):
        return _sanitize_value(value)
    return value


def _company_role_snapshot(caller: CallerContext) -> str | None:
    """取调用人 active 公司角色中的治理代表角色（boss>director>consultant>admin）。"""
    for role in _COMPANY_ROLE_PRIORITY:
        if role in caller.active_company_roles:
            return role
    return None


async def _project_role_snapshot(
    session: AsyncSession, caller: CallerContext, project_id: uuid.UUID | None
) -> str | None:
    """动作涉及某 project 时，按该项目 active 成员关系取项目角色快照。"""
    if project_id is None or project_id not in caller.active_project_ids:
        return None
    return (
        (
            await session.execute(
                select(ProjectMember.project_role).where(
                    ProjectMember.user_id == caller.user_id,
                    ProjectMember.project_id == project_id,
                    ProjectMember.status == MemberStatus.active.value,
                )
            )
        )
        .scalars()
        .first()
    )


async def record_event(
    session: AsyncSession,
    *,
    caller: CallerContext,
    log_type: AuditLogType,
    action: str,
    trace_id: str | None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    before: dict | None = None,
    after: dict | None = None,
    severity: AlertSeverity | None = None,
    risk_level: str | None = None,
    extra: dict | None = None,
    project_id: uuid.UUID | None = None,
) -> AuditEvent:
    """唯一审计写入入口。只 add 进 session，不 commit（由业务事务统一提交）。

    - 角色快照：actor_company_role 取治理代表角色；多角色全集存 extra.actor_company_roles；
      actor_project_role 在 project_id 涉及时按成员关系记录。
    - 脱敏：before/after/extra 经 `_sanitize` 兜底剔除禁止键。
    - 强审计：severity + extra.risk_level 两层标记。
    """
    all_roles = sorted(caller.active_company_roles)
    merged_extra: dict = dict(extra or {})
    if len(all_roles) > 1:
        merged_extra.setdefault("actor_company_roles", all_roles)
    if risk_level is not None:
        merged_extra["risk_level"] = risk_level
    merged_extra = _sanitize(merged_extra)

    event = AuditEvent(
        log_type=log_type.value,
        actor_user_id=caller.user_id,
        actor_company_role=_company_role_snapshot(caller),
        actor_project_role=await _project_role_snapshot(session, caller, project_id),
        action=action,
        target_type=target_type,
        target_id=target_id,
        before_snapshot=_sanitize(before) if before is not None else None,
        after_snapshot=_sanitize(after) if after is not None else None,
        severity=severity.value if severity is not None else None,
        trace_id=trace_id,
        extra=merged_extra or None,
    )
    session.add(event)
    return event


async def record_system_event(
    session: AsyncSession,
    *,
    log_type: AuditLogType,
    action: str,
    trace_id: str,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    before: dict | None = None,
    after: dict | None = None,
    severity: AlertSeverity | None = None,
    risk_level: str | None = None,
    extra: dict | None = None,
) -> AuditEvent:
    """系统触发作业（Celery 扫描）专用审计写入：actor_user_id=None（无业务发起人）。

    只 add 进 session，不 commit（由作业事务统一提交）。脱敏 / 强审计标记口径与
    `record_event` 一致；snapshot / extra 同样兜底剔除禁止键与值级脱敏。
    """
    merged_extra: dict = dict(extra or {})
    if risk_level is not None:
        merged_extra["risk_level"] = risk_level
    merged_extra = _sanitize(merged_extra)
    event = AuditEvent(
        log_type=log_type.value,
        actor_user_id=None,  # 系统作业无业务发起人
        actor_company_role=None,
        actor_project_role=None,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before_snapshot=_sanitize(before) if before is not None else None,
        after_snapshot=_sanitize(after) if after is not None else None,
        severity=severity.value if severity is not None else None,
        trace_id=trace_id,
        extra=merged_extra or None,
    )
    session.add(event)
    return event


async def record_denied(
    session: AsyncSession,
    *,
    caller: CallerContext,
    log_type: AuditLogType,
    action: str,
    trace_id: str | None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    severity: AlertSeverity | None = None,
    risk_level: str | None = None,
    extra: dict | None = None,
    project_id: uuid.UUID | None = None,
) -> None:
    """被拒动作的审计：写事件并立即 commit（随后业务层会 raise）。

    被拒路径通常未写任何业务数据，单独 commit 这条审计是安全的，确保拒绝也留痕。
    """
    await record_event(
        session,
        caller=caller,
        log_type=log_type,
        action=action,
        trace_id=trace_id,
        target_type=target_type,
        target_id=target_id,
        severity=severity,
        risk_level=risk_level,
        extra=extra,
        project_id=project_id,
    )
    await session.commit()


# ============================================================
# 读取 / 查询（Admin Audit API；角色分层 + 视图二次脱敏）
# ============================================================

# admin 元数据视图允许从 extra 透出的安全子集（denied_reason / risk_level 等）。
_ADMIN_EXTRA_WHITELIST = {
    "denied_reason",
    "risk_level",
    "rate_limited",
    "returned_layer",
    "used_access_layer",
    "effective_access_source",
}
# 触及 L5 的事件：admin 视图须隐藏 target_id（避免反查 L5 资产存在性）。
_L5_ACTIONS = {
    AuditAction.l5_original_access.value,
    AuditAction.preview_l5_used.value,
    "agent.l5_access",
}


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"denied_reason": reason, "message": message}
    )


def _is_admin(caller: CallerContext) -> bool:
    return CompanyRole.admin.value in caller.active_company_roles


def _require_audit_reader(caller: CallerContext) -> str:
    """审计查询权：admin 或 boss / 咨询总监；返回视图档位。其余 403。"""
    if caller.can_discover_l5:  # boss / consulting_director
        return "governance"
    if _is_admin(caller):
        return "admin_metadata"
    raise _denied(403, "audit_access_forbidden", "无审计查询权（仅 admin / boss / 咨询总监）")


def _event_is_l5(event: AuditEvent) -> bool:
    if event.action in _L5_ACTIONS:
        return True
    extra = event.extra or {}
    return extra.get("confidentiality_level") == ConfidentialityLevel.L5.value


def _to_out(event: AuditEvent, view: str, names: dict[uuid.UUID, str]) -> AuditEventOut:
    """按视图档位构建脱敏后的审计响应。"""
    extra = event.extra or {}
    denied_reason = extra.get("denied_reason")
    risk_level = extra.get("risk_level")
    actor_name = names.get(event.actor_user_id) if event.actor_user_id else None

    if view == "governance":
        # 业务治理视图：快照 / extra / title / target_id 全可见（技术敏感标识本就不入库）。
        return AuditEventOut(
            id=event.id,
            log_type=event.log_type,
            action=event.action,
            actor_user_id=event.actor_user_id,
            actor_name=actor_name,
            actor_company_role=event.actor_company_role,
            actor_project_role=event.actor_project_role,
            target_type=event.target_type,
            target_id=event.target_id,
            severity=event.severity,
            is_processed=event.is_processed,
            processed_by=event.processed_by,
            processed_at=event.processed_at,
            trace_id=event.trace_id,
            denied_reason=denied_reason,
            risk_level=risk_level,
            created_at=event.created_at,
            before_snapshot=event.before_snapshot,
            after_snapshot=event.after_snapshot,
            extra=event.extra,
        )

    # admin 元数据视图：不回快照；extra 仅安全子集；L5 事件隐藏 target_id。
    safe_extra = {k: v for k, v in extra.items() if k in _ADMIN_EXTRA_WHITELIST}
    target_id = None if _event_is_l5(event) else event.target_id
    return AuditEventOut(
        id=event.id,
        log_type=event.log_type,
        action=event.action,
        actor_user_id=event.actor_user_id,
        actor_name=actor_name,
        actor_company_role=event.actor_company_role,
        actor_project_role=event.actor_project_role,
        target_type=event.target_type,
        target_id=target_id,
        severity=event.severity,
        is_processed=event.is_processed,
        processed_by=event.processed_by,
        processed_at=event.processed_at,
        trace_id=event.trace_id,
        denied_reason=denied_reason,
        risk_level=risk_level,
        created_at=event.created_at,
        before_snapshot=None,
        after_snapshot=None,
        extra=safe_extra or None,
    )


async def _resolve_names(session: AsyncSession, events: list[AuditEvent]) -> dict[uuid.UUID, str]:
    ids = {e.actor_user_id for e in events if e.actor_user_id}
    if not ids:
        return {}
    rows = (await session.execute(select(User.id, User.name).where(User.id.in_(ids)))).all()
    return {r[0]: r[1] for r in rows}


async def query_audit(
    session: AsyncSession,
    caller: CallerContext,
    *,
    log_type: str | None = None,
    action: str | None = None,
    actor_user_id: uuid.UUID | None = None,
    target_type: str | None = None,
    severity: str | None = None,
    is_processed: bool | None = None,
    trace_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = 1,
    page_size: int = 50,
    sort_order: str = "desc",
) -> AuditListResponse:
    """审计查询（按角色脱敏）。"""
    view = _require_audit_reader(caller)

    stmt = select(AuditEvent)
    if log_type:
        stmt = stmt.where(AuditEvent.log_type == log_type)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if actor_user_id:
        stmt = stmt.where(AuditEvent.actor_user_id == actor_user_id)
    if target_type:
        stmt = stmt.where(AuditEvent.target_type == target_type)
    if severity:
        stmt = stmt.where(AuditEvent.severity == severity)
    if is_processed is not None:
        stmt = stmt.where(AuditEvent.is_processed == is_processed)
    if trace_id:
        stmt = stmt.where(AuditEvent.trace_id == trace_id)
    if date_from:
        stmt = stmt.where(AuditEvent.created_at >= date_from)
    if date_to:
        stmt = stmt.where(AuditEvent.created_at <= date_to)

    all_rows = list((await session.execute(stmt)).scalars().all())
    # 排序（按时间），再分页（数据量小，内存分页即可）。
    all_rows.sort(key=lambda e: e.created_at, reverse=(sort_order != "asc"))
    total = len(all_rows)
    page = max(page, 1)
    page_size = max(min(page_size, 200), 1)
    start = (page - 1) * page_size
    rows = all_rows[start : start + page_size]

    names = await _resolve_names(session, rows)
    return AuditListResponse(
        items=[_to_out(e, view, names) for e in rows],
        total=total,
        page=page,
        page_size=page_size,
        view=view,
    )


async def get_trace(
    session: AsyncSession, caller: CallerContext, trace_id: str
) -> AuditTraceResponse:
    """按 trace_id 返回链路全部事件（按查询人可见性脱敏，不放大权限）。"""
    view = _require_audit_reader(caller)
    rows = list(
        (
            await session.execute(
                select(AuditEvent)
                .where(AuditEvent.trace_id == trace_id)
                .order_by(AuditEvent.created_at)
            )
        )
        .scalars()
        .all()
    )
    names = await _resolve_names(session, rows)
    return AuditTraceResponse(
        trace_id=trace_id, items=[_to_out(e, view, names) for e in rows], view=view
    )


async def mark_processed(
    session: AsyncSession, caller: CallerContext, event_id: uuid.UUID
) -> MarkProcessedResponse:
    """标记异常事件已处理。仅 admin；只更新处理三字段，不改写原始事实；处理动作本身落审计。"""
    if not _is_admin(caller):
        raise _denied(403, "audit_mark_forbidden", "仅 admin 可标记审计异常已处理")

    event = (
        await session.execute(select(AuditEvent).where(AuditEvent.id == event_id))
    ).scalar_one_or_none()
    if event is None:
        raise _denied(404, "audit_event_not_found", "审计事件不存在")
    # 非 exception 事件不允许标记处理（处理流程只针对异常日志）。
    if event.log_type != AuditLogType.exception.value:
        raise _denied(422, "audit_event_not_exception", "仅 exception 日志可标记处理")

    # 幂等：已处理则原样返回，不重复写处理事件。
    if not event.is_processed:
        event.is_processed = True
        event.processed_by = caller.user_id
        event.processed_at = _now()
        # 处理动作本身追加一条审计事件（不改原始 action / snapshot / actor）。
        await record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.audit_exception_processed.value,
            trace_id=event.trace_id,
            target_type="audit_event",
            target_id=event.id,
            extra={"processed_event_action": event.action},
        )
        await session.commit()

    return MarkProcessedResponse(
        event_id=event.id,
        is_processed=event.is_processed,
        processed_by=event.processed_by,
        processed_at=event.processed_at,
    )

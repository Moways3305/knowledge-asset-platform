"""运维告警信号扫描作业（PBC-28 最小告警环）。

对三类高价值运维信号做阈值检查，超阈值时写系统审计 + 给 active admin 写
notification_records（默认渠道走 `default_notification_channel`，由既有
`notifications.dispatch_pending` beat 任务真实下发；企微未启用时保持 in_app
pending，不假装已发送）：

- index_failed_backlog：活跃版本（资产未删除）中 index_status=index_failed 的数量。
- parse_stalled_backlog：weknora_parse_status 停留在 pending/processing 超过判定
  时长（以 indexed_at（上传完成≈解析开始）回退 created_at 为起点）的活跃版本数。
- login_guard_backlog：最近时间窗内 auth_login_attempts 中 locked/rate_limited
  事件数（PBC-18 专表，结构化 result 字段，比扫审计大表更可靠/便宜）。

阈值 / 时间窗 / 冷却均来自 alert_rules（`alert.DEFAULT_OPS_ALERT_RULES` 落库的可
配置默认值）：计数规则停用即关闭对应信号；参数规则（分钟数）停用/缺失回退默认。

冷却去重（状态持久化在 notification_records，beat/worker 重启不重发、不轰炸）：
- 同一信号距上一条同标题通知不足冷却期（默认 360 分钟）→ 不重发；
- 持续超阈值 → 每个冷却期至多 1 条（不永久哑火）；
- 恢复（低于阈值）→ 不发；冷却期满后再次超阈值 → 再发。

安全边界：通知与审计 extra 只含信号类型 / 计数 / 阈值 / 时间窗 / 安全 error_code
聚合。**绝不**含资产标题 / owner / 文件名 / 原文 / weknora kb·doc id / storage·source
ref / email / IP / identifier·ip hash（含前缀）/ token / cookie / 密钥 / 上游原始报错。
告警是系统运维信息（admin 可见可配置），不构成 admin 接触业务内容的旁路。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.utils import utc_now
from app.models.auth_security import AuthLoginAttempt
from app.models.identity import User, UserCompanyRole
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.lifecycle import AlertRule, NotificationRecord
from app.schemas.enums import AssetStatus, AuditAction, AuditLogType, CompanyRole
from app.services import alert as alert_service
from app.services import audit as audit_service

# 规则名（与 alert.DEFAULT_OPS_ALERT_RULES 落库名一致）。
RULE_INDEX_FAILED = "索引失败堆积告警"
RULE_PARSE_STALLED = "解析停滞堆积告警"
RULE_LOGIN_GUARD = "登录安全异常告警"
RULE_PARSE_STALL_MINUTES = "解析停滞判定时长"
RULE_LOGIN_WINDOW_MINUTES = "登录安全统计时间窗"
RULE_COOLDOWN_MINUTES = "运维告警冷却期"

# 通知标题常量：既是用户可读标题，也是冷却去重的匹配键（精确等值查询）。
TITLE_INDEX_FAILED = "运维告警：索引失败堆积"
TITLE_PARSE_STALLED = "运维告警：解析停滞堆积"
TITLE_LOGIN_GUARD = "运维告警：登录安全异常"

SIGNAL_INDEX_FAILED = "index_failed_backlog"
SIGNAL_PARSE_STALLED = "parse_stalled_backlog"
SIGNAL_LOGIN_GUARD = "login_guard_backlog"

# 参数规则停用/缺失时的回退默认（分钟）。
DEFAULT_PARSE_STALL_MINUTES = 120
DEFAULT_LOGIN_WINDOW_MINUTES = 15
DEFAULT_COOLDOWN_MINUTES = 360

# 计入登录安全信号的结果（守卫拦截事实，不含普通 failed）。
_GUARD_RESULTS = ("locked", "rate_limited")
_STALLED_PARSE_STATUSES = ("pending", "processing")


def _as_aware(dt: datetime) -> datetime:
    """SQLite 读回的 naive datetime 视作 UTC（PostgreSQL 为 aware）。"""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


async def _load_rules(session: AsyncSession) -> dict[str, AlertRule]:
    rows = (await session.execute(select(AlertRule))).scalars().all()
    return {r.rule_name: r for r in rows}


def _param_minutes(rules: dict[str, AlertRule], name: str, default: int) -> int:
    """参数规则取值（分钟）：缺失/停用/非法 → 默认；钳制 >= 1。"""
    rule = rules.get(name)
    if rule is None or not rule.enabled or rule.threshold is None:
        return max(1, default)
    try:
        v = int(rule.threshold)
    except (TypeError, ValueError):
        return max(1, default)
    return v if v >= 1 else max(1, default)


def _active_version_conditions():
    """与 /admin/ops/indexing 同口径：活跃版本 + 资产未删除。"""
    return (
        KnowledgeAssetVersion.version_status == "active",
        KnowledgeAsset.asset_status != AssetStatus.deleted.value,
    )


def _version_count_stmt(*conds):
    return (
        select(func.count())
        .select_from(KnowledgeAssetVersion)
        .join(KnowledgeAsset, KnowledgeAssetVersion.asset_id == KnowledgeAsset.id)
        .where(*_active_version_conditions(), *conds)
    )


async def _count_index_failed(session: AsyncSession) -> int:
    stmt = _version_count_stmt(KnowledgeAssetVersion.index_status == "index_failed")
    return int((await session.execute(stmt)).scalar() or 0)


async def _index_failed_error_codes(session: AsyncSession, limit: int = 5) -> dict[str, int]:
    """失败安全 error_code 聚合（仅 code 与计数；error_message / 标题绝不进聚合）。"""
    rows = (
        await session.execute(
            select(KnowledgeAssetVersion.index_error_code, func.count())
            .select_from(KnowledgeAssetVersion)
            .join(KnowledgeAsset, KnowledgeAssetVersion.asset_id == KnowledgeAsset.id)
            .where(
                *_active_version_conditions(),
                KnowledgeAssetVersion.index_status == "index_failed",
            )
            .group_by(KnowledgeAssetVersion.index_error_code)
            .order_by(func.count().desc())
            .limit(limit)
        )
    ).all()
    return {(code or "unknown"): int(n) for code, n in rows}


async def _count_parse_stalled(session: AsyncSession, now: datetime, stall_minutes: int) -> int:
    cutoff = now - timedelta(minutes=stall_minutes)
    stmt = _version_count_stmt(
        KnowledgeAssetVersion.weknora_parse_status.in_(_STALLED_PARSE_STATUSES),
        func.coalesce(KnowledgeAssetVersion.indexed_at, KnowledgeAssetVersion.created_at) <= cutoff,
    )
    return int((await session.execute(stmt)).scalar() or 0)


async def _count_login_guard_events(
    session: AsyncSession, now: datetime, window_minutes: int
) -> int:
    window_start = now - timedelta(minutes=window_minutes)
    stmt = (
        select(func.count())
        .select_from(AuthLoginAttempt)
        .where(
            AuthLoginAttempt.result.in_(_GUARD_RESULTS),
            AuthLoginAttempt.created_at >= window_start,
        )
    )
    return int((await session.execute(stmt)).scalar() or 0)


async def _in_cooldown(
    session: AsyncSession, title: str, now: datetime, cooldown_minutes: int
) -> bool:
    """距上一条同标题通知是否不足冷却期。状态在 DB，重启后口径不变。"""
    latest = (
        await session.execute(
            select(NotificationRecord.created_at)
            .where(NotificationRecord.title == title)
            .order_by(NotificationRecord.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest is None:
        return False
    return now < _as_aware(latest) + timedelta(minutes=cooldown_minutes)


async def _active_admin_ids(session: AsyncSession) -> list:
    rows = (
        await session.execute(
            select(User.id)
            .join(UserCompanyRole, UserCompanyRole.user_id == User.id)
            .where(
                User.status == "active",
                UserCompanyRole.company_role == CompanyRole.admin.value,
                UserCompanyRole.status == "active",
            )
            .distinct()
        )
    ).scalars()
    return list(rows)


async def _emit(
    session: AsyncSession,
    *,
    rule: AlertRule,
    signal: str,
    title: str,
    content: str,
    extra: dict,
    trace_id: str | None,
    admins: list,
) -> None:
    """系统审计 + 每个 active admin 一条通知（默认渠道，复用既有 dispatch 链路）。"""
    from app.services.wecom_notification import default_notification_channel

    audit_event = await audit_service.record_system_event(
        session,
        log_type=AuditLogType.operation,
        action=AuditAction.ops_alert_triggered.value,
        trace_id=trace_id or "",
        target_type="alert_rule",
        target_id=rule.id,
        extra=extra,
    )
    await session.flush()
    channel = default_notification_channel()
    for admin_id in admins:
        await alert_service.record_local_notification(
            session,
            recipient_user_id=admin_id,
            title=title,
            content=content,
            audit_event_id=audit_event.id,
            channel=channel,
            alert_rule_id=rule.id,
        )


async def scan_ops_alerts(
    session: AsyncSession,
    *,
    trace_id: str | None = None,
    now: datetime | None = None,
) -> dict:
    """扫描三类运维信号，超阈值且不在冷却期 → 审计 + admin 通知。返回安全计数。

    WeKnora / 企微未配置的本地环境安全降级：无底座 → 索引/解析计数自然为 0，安全
    空跑；企微未启用 → 通知渠道为 in_app、保持 pending（admin 面板可见，不外发、
    不假装已发送）。
    """
    await alert_service.ensure_default_rules(session)
    now = _as_aware(now or utc_now())
    rules = await _load_rules(session)
    cooldown = _param_minutes(rules, RULE_COOLDOWN_MINUTES, DEFAULT_COOLDOWN_MINUTES)

    triggered: list[str] = []
    counts: dict[str, int] = {}
    admins: list | None = None  # 首个触发信号时再查询。

    async def _admins() -> list:
        nonlocal admins
        if admins is None:
            admins = await _active_admin_ids(session)
        return admins

    # ---- 信号一：索引失败堆积 ----
    rule = rules.get(RULE_INDEX_FAILED)
    if rule is not None and rule.enabled and rule.threshold is not None:
        threshold = int(rule.threshold)
        count = await _count_index_failed(session)
        counts[SIGNAL_INDEX_FAILED] = count
        if count >= threshold and not await _in_cooldown(
            session, TITLE_INDEX_FAILED, now, cooldown
        ):
            codes = await _index_failed_error_codes(session)
            codes_text = "、".join(f"{c}×{n}" for c, n in codes.items()) or "unknown"
            await _emit(
                session,
                rule=rule,
                signal=SIGNAL_INDEX_FAILED,
                title=TITLE_INDEX_FAILED,
                content=(
                    f"活跃版本中索引失败 {count} 个，达到阈值 {threshold}。"
                    f"失败码分布：{codes_text}。请在运维面板重试索引或排查底座配置。"
                ),
                extra={
                    "signal": SIGNAL_INDEX_FAILED,
                    "count": count,
                    "threshold": threshold,
                    "error_codes": codes,
                },
                trace_id=trace_id,
                admins=await _admins(),
            )
            triggered.append(SIGNAL_INDEX_FAILED)

    # ---- 信号二：解析停滞堆积 ----
    rule = rules.get(RULE_PARSE_STALLED)
    if rule is not None and rule.enabled and rule.threshold is not None:
        threshold = int(rule.threshold)
        stall_minutes = _param_minutes(rules, RULE_PARSE_STALL_MINUTES, DEFAULT_PARSE_STALL_MINUTES)
        count = await _count_parse_stalled(session, now, stall_minutes)
        counts[SIGNAL_PARSE_STALLED] = count
        if count >= threshold and not await _in_cooldown(
            session, TITLE_PARSE_STALLED, now, cooldown
        ):
            await _emit(
                session,
                rule=rule,
                signal=SIGNAL_PARSE_STALLED,
                title=TITLE_PARSE_STALLED,
                content=(
                    f"有 {count} 个活跃版本的解析状态停留在 pending/processing 超过 "
                    f"{stall_minutes} 分钟，达到阈值 {threshold}。"
                    "可在运维面板触发重新解析或检查底座对账任务。"
                ),
                extra={
                    "signal": SIGNAL_PARSE_STALLED,
                    "count": count,
                    "threshold": threshold,
                    "stall_minutes": stall_minutes,
                },
                trace_id=trace_id,
                admins=await _admins(),
            )
            triggered.append(SIGNAL_PARSE_STALLED)

    # ---- 信号三：登录安全异常 ----
    rule = rules.get(RULE_LOGIN_GUARD)
    if rule is not None and rule.enabled and rule.threshold is not None:
        threshold = int(rule.threshold)
        window_minutes = _param_minutes(
            rules, RULE_LOGIN_WINDOW_MINUTES, DEFAULT_LOGIN_WINDOW_MINUTES
        )
        count = await _count_login_guard_events(session, now, window_minutes)
        counts[SIGNAL_LOGIN_GUARD] = count
        if count >= threshold and not await _in_cooldown(session, TITLE_LOGIN_GUARD, now, cooldown):
            await _emit(
                session,
                rule=rule,
                signal=SIGNAL_LOGIN_GUARD,
                title=TITLE_LOGIN_GUARD,
                content=(
                    f"最近 {window_minutes} 分钟内发生登录锁定/限流事件 {count} 起，"
                    f"达到阈值 {threshold}。请关注登录安全运维面板，必要时收紧风控参数。"
                ),
                extra={
                    "signal": SIGNAL_LOGIN_GUARD,
                    "count": count,
                    "threshold": threshold,
                    "window_minutes": window_minutes,
                },
                trace_id=trace_id,
                admins=await _admins(),
            )
            triggered.append(SIGNAL_LOGIN_GUARD)

    await session.commit()
    return {
        "triggered": triggered,
        "counts": counts,
        "notifications": len(triggered) * len(admins or []),
    }

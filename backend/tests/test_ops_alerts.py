"""最小运维告警环测试。

覆盖三类信号（索引失败堆积 / 解析停滞堆积 / 登录安全异常）的：
- 阈值触发与未达阈值不触发；
- 规则停用即关闭信号；
- 冷却去重（同冷却期内不重发；冷却期满重发；状态在 DB，等价于 beat 重启不重发）；
- 通知/审计只含安全元数据（标题 / hash / email / kb id / storage ref 不外泄）；
- 通知走既有 notification_records + 默认渠道（未配企微 → in_app pending，不假发送）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.audit import AuditEvent
from app.models.auth_security import AuthLoginAttempt
from app.models.identity import User, UserCompanyRole
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.lifecycle import AlertRule, NotificationRecord
from app.seed.dev_seed import USER_ADMIN_ONLY
from app.services import alert as alert_service
from app.services.jobs import ops_alerts

AUDIT_ACTION = "ops.alert_triggered"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _set_rule(session, name: str, *, threshold: float | None = None, enabled: bool | None = None):
    """调整某条告警规则（测试前先确保默认规则已落库）。"""
    await alert_service.ensure_default_rules(session)
    rule = (
        await session.execute(select(AlertRule).where(AlertRule.rule_name == name))
    ).scalar_one()
    if threshold is not None:
        rule.threshold = threshold
    if enabled is not None:
        rule.enabled = enabled
    await session.commit()
    return rule


async def _mark_index_failed(session, n: int, *, code: str = "weknora_upload_failed") -> list:
    """把 n 个 seed 活跃版本标为 index_failed（安全 error_code）。"""
    versions = list(
        (
            await session.execute(
                select(KnowledgeAssetVersion)
                .where(KnowledgeAssetVersion.version_status == "active")
                .limit(n)
            )
        ).scalars().all()
    )
    assert len(versions) >= n, "seed 活跃版本不足"
    for v in versions:
        v.index_status = "index_failed"
        v.index_error_code = code
    await session.commit()
    return versions


async def _active_versions(session, n: int) -> list[KnowledgeAssetVersion]:
    rows = list(
        (
            await session.execute(
                select(KnowledgeAssetVersion)
                .where(KnowledgeAssetVersion.version_status == "active")
                .limit(n)
            )
        ).scalars().all()
    )
    assert len(rows) >= n, "seed 活跃版本不足"
    return rows


async def _notifications(session, title: str, recipient=None) -> list[NotificationRecord]:
    stmt = select(NotificationRecord).where(NotificationRecord.title == title)
    if recipient is not None:
        stmt = stmt.where(NotificationRecord.recipient_user_id == recipient)
    return list((await session.execute(stmt)).scalars().all())


async def _audit_events(session, action: str = AUDIT_ACTION) -> list[AuditEvent]:
    return list(
        (await session.execute(select(AuditEvent).where(AuditEvent.action == action))).scalars().all()
    )


# ---------------------------------------------------------------------------
# 信号一：索引失败堆积
# ---------------------------------------------------------------------------
async def test_index_failed_backlog_triggers_admin_notification(db_session):
    await _set_rule(db_session, ops_alerts.RULE_INDEX_FAILED, threshold=2)
    await _mark_index_failed(db_session, 3)

    result = await ops_alerts.scan_ops_alerts(db_session, trace_id="t-ops")

    assert "index_failed_backlog" in result["triggered"]
    notifs = await _notifications(db_session, ops_alerts.TITLE_INDEX_FAILED)
    assert notifs, "应产生索引失败堆积通知"
    # 收件人是 active admin（系统运维信息），admin E 必在其中。
    recipients = {n.recipient_user_id for n in notifs}
    assert USER_ADMIN_ONLY in recipients
    # 通知挂到对应规则；新建状态 pending（无企微配置时不假装已发送）。
    for n in notifs:
        assert n.send_status == "pending"
        assert n.alert_rule_id is not None
        assert "3" in n.content and "2" in n.content  # 计数与阈值
    # 审计事件（系统）记录信号与计数。
    events = await _audit_events(db_session)
    assert len(events) == 1
    extra = events[0].extra or {}
    assert extra.get("signal") == "index_failed_backlog"
    assert extra.get("count") == 3
    assert extra.get("threshold") == 2


async def test_index_failed_below_threshold_no_notification(db_session):
    await _set_rule(db_session, ops_alerts.RULE_INDEX_FAILED, threshold=5)
    await _mark_index_failed(db_session, 2)

    result = await ops_alerts.scan_ops_alerts(db_session, trace_id="t-ops")

    assert "index_failed_backlog" not in result["triggered"]
    assert await _notifications(db_session, ops_alerts.TITLE_INDEX_FAILED) == []


async def test_disabled_rule_skips_signal(db_session):
    await _set_rule(db_session, ops_alerts.RULE_INDEX_FAILED, threshold=1, enabled=False)
    await _mark_index_failed(db_session, 3)

    result = await ops_alerts.scan_ops_alerts(db_session, trace_id="t-ops")

    assert "index_failed_backlog" not in result["triggered"]
    assert await _notifications(db_session, ops_alerts.TITLE_INDEX_FAILED) == []


# ---------------------------------------------------------------------------
# 信号二：解析停滞堆积
# ---------------------------------------------------------------------------
async def test_parse_stalled_counts_only_old_pending(db_session):
    await _set_rule(db_session, ops_alerts.RULE_PARSE_STALLED, threshold=2)
    versions = await _active_versions(db_session, 3)
    old = _now() - timedelta(hours=3)
    # 两个停滞超过默认 120 分钟；一个刚开始解析（不算停滞）。
    versions[0].weknora_parse_status = "pending"
    versions[0].indexed_at = old
    versions[1].weknora_parse_status = "processing"
    versions[1].indexed_at = old
    versions[2].weknora_parse_status = "pending"
    versions[2].indexed_at = _now()
    await db_session.commit()

    result = await ops_alerts.scan_ops_alerts(db_session, trace_id="t-ops")

    assert "parse_stalled_backlog" in result["triggered"]
    assert result["counts"]["parse_stalled_backlog"] == 2
    notifs = await _notifications(db_session, ops_alerts.TITLE_PARSE_STALLED, USER_ADMIN_ONLY)
    assert len(notifs) == 1


# ---------------------------------------------------------------------------
# 信号三：登录安全异常
# ---------------------------------------------------------------------------
async def _add_attempt(session, *, result: str, created_at: datetime | None = None) -> None:
    attempt = AuthLoginAttempt(
        identifier_hash="a" * 64,
        identifier_hint=("a" * 64)[:12],
        ip_hash="b" * 64,
        login_method="password",
        result=result,
        reason_code="identifier_locked" if result == "locked" else "ip_rate_limited",
        trace_id="t-login",
    )
    if created_at is not None:
        attempt.created_at = created_at
    session.add(attempt)


async def test_login_guard_signal_counts_recent_window_only(db_session):
    await _set_rule(db_session, ops_alerts.RULE_LOGIN_GUARD, threshold=2)
    # 窗口内 2 起（locked + rate_limited）；窗口外 1 起不计。
    await _add_attempt(db_session, result="locked")
    await _add_attempt(db_session, result="rate_limited")
    await _add_attempt(db_session, result="locked", created_at=_now() - timedelta(hours=2))
    # 普通失败（failed）不计入告警信号。
    await _add_attempt(db_session, result="failed")
    await db_session.commit()

    result = await ops_alerts.scan_ops_alerts(db_session, trace_id="t-ops")

    assert "login_guard_backlog" in result["triggered"]
    assert result["counts"]["login_guard_backlog"] == 2
    notifs = await _notifications(db_session, ops_alerts.TITLE_LOGIN_GUARD, USER_ADMIN_ONLY)
    assert len(notifs) == 1


# ---------------------------------------------------------------------------
# 冷却去重
# ---------------------------------------------------------------------------
async def test_cooldown_suppresses_repeat_within_window(db_session):
    """持续超阈值：冷却期内重复扫描只发 1 条（含 beat 重启场景——状态在 DB）。"""
    await _set_rule(db_session, ops_alerts.RULE_INDEX_FAILED, threshold=1)
    await _mark_index_failed(db_session, 2)

    await ops_alerts.scan_ops_alerts(db_session, trace_id="t-1")
    await ops_alerts.scan_ops_alerts(db_session, trace_id="t-2")
    await ops_alerts.scan_ops_alerts(db_session, trace_id="t-3")

    notifs = await _notifications(db_session, ops_alerts.TITLE_INDEX_FAILED, USER_ADMIN_ONLY)
    assert len(notifs) == 1, "冷却期内不得重复发送"
    assert len(await _audit_events(db_session)) == 1


async def test_resend_after_cooldown_expiry(db_session):
    """持续超阈值跨冷却期：每个冷却期至多 1 条（不轰炸、不永久哑火）。"""
    await _set_rule(db_session, ops_alerts.RULE_INDEX_FAILED, threshold=1)
    await _mark_index_failed(db_session, 2)

    await ops_alerts.scan_ops_alerts(db_session, trace_id="t-1")
    # 冷却期默认 360 分钟；7 小时后再扫 → 重发。
    await ops_alerts.scan_ops_alerts(
        db_session, trace_id="t-2", now=_now() + timedelta(hours=7)
    )

    notifs = await _notifications(db_session, ops_alerts.TITLE_INDEX_FAILED, USER_ADMIN_ONLY)
    assert len(notifs) == 2


async def test_recovered_signal_emits_nothing(db_session):
    """信号恢复（低于阈值）后扫描不发新通知。"""
    await _set_rule(db_session, ops_alerts.RULE_INDEX_FAILED, threshold=1)
    versions = await _mark_index_failed(db_session, 2)

    await ops_alerts.scan_ops_alerts(db_session, trace_id="t-1")
    # 修复：失败清零。
    for v in versions:
        v.index_status = "indexed"
        v.index_error_code = None
    await db_session.commit()

    result = await ops_alerts.scan_ops_alerts(
        db_session, trace_id="t-2", now=_now() + timedelta(hours=7)
    )

    assert "index_failed_backlog" not in result["triggered"]
    notifs = await _notifications(db_session, ops_alerts.TITLE_INDEX_FAILED, USER_ADMIN_ONLY)
    assert len(notifs) == 1


# ---------------------------------------------------------------------------
# 无泄漏：通知与审计只含安全元数据
# ---------------------------------------------------------------------------
async def test_notification_and_audit_no_leak(db_session):
    await _set_rule(db_session, ops_alerts.RULE_INDEX_FAILED, threshold=1)
    await _set_rule(db_session, ops_alerts.RULE_PARSE_STALLED, threshold=1)
    await _set_rule(db_session, ops_alerts.RULE_LOGIN_GUARD, threshold=1)

    # 敏感哨兵：资产标题 / owner email 来自 seed；标题改成显式哨兵。
    versions = await _mark_index_failed(db_session, 2)
    asset = await db_session.get(KnowledgeAsset, versions[0].asset_id)
    asset.title = "绝密客户尽调报告-哨兵"
    versions[1].weknora_parse_status = "pending"
    versions[1].indexed_at = _now() - timedelta(hours=5)
    await _add_attempt(db_session, result="locked")
    await db_session.commit()

    await ops_alerts.scan_ops_alerts(db_session, trace_id="t-ops")

    notifs = list(
        (
            await db_session.execute(
                select(NotificationRecord).where(
                    NotificationRecord.title.in_(
                        [
                            ops_alerts.TITLE_INDEX_FAILED,
                            ops_alerts.TITLE_PARSE_STALLED,
                            ops_alerts.TITLE_LOGIN_GUARD,
                        ]
                    )
                )
            )
        ).scalars().all()
    )
    assert notifs
    events = await _audit_events(db_session)
    assert events

    blobs = [f"{n.title}\n{n.content}" for n in notifs]
    blobs += [str(e.extra) for e in events]
    forbidden = [
        "哨兵",            # 资产标题
        "@dev.local",      # email
        "a" * 12,          # identifier_hash 及其前缀
        "b" * 12,          # ip_hash 及其前缀
        "wk-kb",           # weknora kb id（seed 形态）
        "wk-doc",          # weknora doc id
        "storage",         # storage ref 类
        "download_url",
    ]
    for blob in blobs:
        for marker in forbidden:
            assert marker not in blob, f"通知/审计泄漏敏感串：{marker} in {blob}"


async def test_index_failed_content_aggregates_safe_error_codes(db_session):
    """计数聚合只带安全 error_code，绝不带 error_message / 标题。"""
    await _set_rule(db_session, ops_alerts.RULE_INDEX_FAILED, threshold=1)
    versions = await _mark_index_failed(db_session, 2, code="weknora_upload_failed")
    versions[0].index_error_message = "上游原始报错-不得外泄"
    await db_session.commit()

    await ops_alerts.scan_ops_alerts(db_session, trace_id="t-ops")

    notifs = await _notifications(db_session, ops_alerts.TITLE_INDEX_FAILED, USER_ADMIN_ONLY)
    assert len(notifs) == 1
    assert "weknora_upload_failed" in notifs[0].content
    assert "不得外泄" not in notifs[0].content


# ---------------------------------------------------------------------------
# 收件人边界
# ---------------------------------------------------------------------------
async def test_recipients_are_active_admins_only(db_session):
    await _set_rule(db_session, ops_alerts.RULE_INDEX_FAILED, threshold=1)
    await _mark_index_failed(db_session, 2)

    await ops_alerts.scan_ops_alerts(db_session, trace_id="t-ops")

    notifs = await _notifications(db_session, ops_alerts.TITLE_INDEX_FAILED)
    recipients = {n.recipient_user_id for n in notifs}
    # 与 active admin 集合一致。
    admin_ids = {
        row[0]
        for row in (
            await db_session.execute(
                select(User.id)
                .join(UserCompanyRole, UserCompanyRole.user_id == User.id)
                .where(
                    User.status == "active",
                    UserCompanyRole.company_role == "admin",
                    UserCompanyRole.status == "active",
                )
            )
        ).all()
    }
    assert recipients == admin_ids
    assert len(recipients) == len(notifs), "每个 admin 一条，不重复"


async def test_scan_without_signals_is_quiet(db_session):
    """无信号时空跑：不写通知、不写审计、不报错（WeKnora/企微未配置的本地降级）。"""
    result = await ops_alerts.scan_ops_alerts(db_session, trace_id="t-ops")

    assert result["triggered"] == []
    assert await _audit_events(db_session) == []
    all_ops_titles = [
        ops_alerts.TITLE_INDEX_FAILED,
        ops_alerts.TITLE_PARSE_STALLED,
        ops_alerts.TITLE_LOGIN_GUARD,
    ]
    rows = list(
        (
            await db_session.execute(
                select(NotificationRecord).where(NotificationRecord.title.in_(all_ops_titles))
            )
        ).scalars().all()
    )
    assert rows == []

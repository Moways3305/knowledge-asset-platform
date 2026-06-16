"""Knowledge 运营洞察 API 测试。

覆盖：
- 普通业务用户只看本人/所在项目范围的安全聚合；跨范围资产不计入；
- 纯 admin 系统运维聚合但 title_visible=false，recent_items 无标题/owner/文件名；
- boss/咨询总监治理范围聚合 + title-visible drilldown；
- indexing / access / lifecycle 统计来自真实表；
- 非业务非 admin → 403；
- 响应不泄露 WeKnora id / storage·source ref / 文件名 / token。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.models.identity import User
from app.models.indexing_job import IndexingOperationJob
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.lifecycle import AssetLifecycleEvent
from app.models.original_access import OriginalAccessRequest
from app.models.permission_rule import PermissionRule
from app.seed.dev_seed import (
    KA_COMPANY_L2,
    PROJECT_ALPHA,
    PROJECT_BETA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_PROJECT_MANAGER,
)

INSIGHTS = "/api/v1/knowledge/ops-insights"
_LEAK_TOKENS = ["wk-kb", "wk-doc", "weknora_kb_id", "weknora_doc_id", "storage_ref",
                "source_file_ref", "download_url", "api_key", "sk-", "cookie", "secret.txt"]


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


def _now():
    return datetime.now(timezone.utc)


def _assert_no_leak(text):
    for t in _LEAK_TOKENS:
        assert t not in text, f"响应不应泄露 {t}"


async def _insert_index_failed_asset(db_session, *, scope="project", project_id=PROJECT_ALPHA, owner=USER_CONSULTANT, title="索引失败资产", doc="wk-doc-stale", asset_status="active"):
    asset_id = uuid.uuid4()
    asset = KnowledgeAsset(
        id=asset_id, title=title, scope=scope, zone="material", asset_type="deliverable",
        owner_user_id=owner, maintainer_user_id=owner,
        project_id=project_id if scope == "project" else None,
        visibility="project_only", confidentiality_level="L2", ai_access_level="A2",
        asset_status=asset_status, lifecycle_phase_key="交付",
    )
    version = KnowledgeAssetVersion(
        asset_id=asset_id, version_no="v1", version_status="active", created_by=owner,
        # server-only 内部标识（用于无泄露断言）。
        weknora_kb_id="wk-kb-secret", weknora_doc_id=doc, weknora_parse_status="failed",
        index_status="index_failed", index_error_code="weknora_call_failed",
    )
    asset.versions.append(version)
    asset.current_version_id = version.id
    db_session.add(asset)
    await db_session.commit()
    return str(asset_id)


async def _insert_request(db_session, *, asset_id, requester, status, reviewer=None, created_at=None, reviewed_at=None):
    req = OriginalAccessRequest(
        asset_id=asset_id, requester_user_id=requester, status=status,
        requested_access_layer="original", reviewer_user_id=reviewer,
        reviewed_at=reviewed_at,
    )
    if created_at is not None:
        req.created_at = created_at
    db_session.add(req)
    await db_session.commit()


# ---------------------------------------------------------------------------
# 权限矩阵
# ---------------------------------------------------------------------------
async def test_non_business_non_admin_forbidden(client, db_session):
    """无公司角色（非业务、非 admin）→ 403。"""
    uid = uuid.uuid4()
    u = User(id=uid, name="无角色用户", email=f"norole-{uid}@dev.local", status="active")
    db_session.add(u)
    await db_session.commit()
    r = await client.get(INSIGHTS, headers=_hdr(uid))
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "insights_forbidden"


async def test_consultant_sees_own_project_scope_only(client, db_session):
    mine = await _insert_index_failed_asset(db_session, scope="project", project_id=PROJECT_ALPHA, title="我项目的失败资产")
    # 另一个项目（consultant 非成员）的失败资产 → 不计入 consultant 视图。
    other = await _insert_index_failed_asset(db_session, scope="project", project_id=PROJECT_BETA, owner=USER_BOSS, title="他项目失败资产", doc="wk-doc-other")
    r = await client.get(INSIGHTS, headers=_hdr(USER_CONSULTANT))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title_visible"] is True
    assert body["indexing"]["index_failed"] >= 1
    ids = {it["asset_id"] for it in body["recent_items"]}
    assert mine in ids
    assert other not in ids  # 跨项目失败资产不下钻
    # 普通业务用户不获取系统 ops 作业列表。
    assert body["indexing"]["recent_jobs"] == []
    _assert_no_leak(r.text)


async def test_pure_admin_title_hidden_but_counts_present(client, db_session):
    await _insert_index_failed_asset(db_session, scope="company", project_id=None, owner=USER_BOSS, title="公司机密标题不可见", doc="wk-doc-co")
    # 入一条 ops 作业，admin 可见安全摘要。
    db_session.add(IndexingOperationJob(operation_type="retry_index", status="completed_with_errors",
                                        scope_filter={"scope": "all"}, requested_by_user_id=USER_ADMIN_ONLY,
                                        total_count=2, success_count=1, failed_count=1))
    await db_session.commit()
    r = await client.get(INSIGHTS, headers=_hdr(USER_ADMIN_ONLY))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title_visible"] is False
    assert body["indexing"]["index_failed"] >= 1  # 系统运维聚合可见
    # recent_items 标题隐藏（无业务标题 / owner / 文件名）。
    for it in body["recent_items"]:
        assert it["title"] is None
    assert "公司机密标题不可见" not in r.text
    # admin（ops viewer）可见最近作业安全摘要。
    assert len(body["indexing"]["recent_jobs"]) >= 1
    job = body["indexing"]["recent_jobs"][0]
    assert "total_count" in job and "status" in job
    _assert_no_leak(r.text)


async def test_governance_title_visible_and_company_scope(client, db_session):
    cid = await _insert_index_failed_asset(db_session, scope="company", project_id=None, owner=USER_BOSS, title="公司失败资产", doc="wk-doc-gov")
    r = await client.get(INSIGHTS, headers=_hdr(USER_BOSS))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title_visible"] is True
    ids = {it["asset_id"] for it in body["recent_items"]}
    assert cid in ids
    titles = {it["title"] for it in body["recent_items"] if it["asset_id"] == cid}
    assert "公司失败资产" in titles
    _assert_no_leak(r.text)


# ---------------------------------------------------------------------------
# 真实统计来源
# ---------------------------------------------------------------------------
async def test_indexing_counts_from_real_versions(client, db_session):
    await _insert_index_failed_asset(db_session, scope="project", project_id=PROJECT_ALPHA, title="失败1", doc="wk-doc-1")
    await _insert_index_failed_asset(db_session, scope="project", project_id=PROJECT_ALPHA, title="失败2", doc="wk-doc-2")
    r = await client.get(INSIGHTS, headers=_hdr(USER_PROJECT_MANAGER))
    body = r.json()
    assert body["indexing"]["index_failed"] >= 2
    assert body["indexing"]["parse_failed"] >= 2  # 上面 fixture parse_status=failed
    # 卡片来自真实计数（非零才出现）。
    keys = {c["key"] for c in body["cards"]}
    assert "index_failed" in keys


async def test_access_stats_pending_and_auto_approved(client, db_session):
    # 在公司资产上构造 pending + 自动审批（reviewer=None）申请，治理可见。
    await _insert_request(db_session, asset_id=KA_COMPANY_L2, requester=USER_CONSULTANT, status="pending")
    await _insert_request(db_session, asset_id=KA_COMPANY_L2, requester=USER_PROJECT_MANAGER, status="approved",
                          reviewer=None, reviewed_at=_now())
    r = await client.get(INSIGHTS, headers=_hdr(USER_BOSS))
    body = r.json()
    assert body["access"]["pending_original_requests"] >= 1
    assert body["access"]["recent_auto_approved"] >= 1


async def test_overdue_requires_timeout_rule(client, db_session):
    # 启用 access_request_timeout_hours=24 规则 + 一条 25h 前的 pending 申请 → overdue 计入。
    db_session.add(PermissionRule(
        rule_key="access_request_timeout_hours", rule_group="access_request", rule_type="numeric",
        display_name="访问申请自动通过时限", value_number=24, default_number=24, unit="小时", enabled=True,
    ))
    await db_session.commit()
    await _insert_request(db_session, asset_id=KA_COMPANY_L2, requester=USER_CONSULTANT, status="pending",
                          created_at=_now() - timedelta(hours=25))
    r = await client.get(INSIGHTS, headers=_hdr(USER_BOSS))
    body = r.json()
    assert body["access"]["timeout_enabled"] is True
    assert body["access"]["overdue_original_requests"] >= 1
    # overdue 应触发一条审批建议。
    keys = {rec["key"] for rec in body["recommendations"]}
    assert "review_overdue_requests" in keys


# ---------------------------------------------------------------------------
# 空态 / 参数
# ---------------------------------------------------------------------------
async def test_empty_state_honest(client):
    """无任何运营项时：cards 为空，counts 为 0（不造假数字）。"""
    r = await client.get(INSIGHTS, headers=_hdr(USER_CONSULTANT))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cards"] == []
    assert body["indexing"]["index_failed"] == 0
    assert body["recommendations"] == []


async def test_days_and_limit_clamped(client, db_session):
    r = await client.get(INSIGHTS + "?days=9999&limit=9999", headers=_hdr(USER_BOSS))
    body = r.json()
    assert body["window_days"] == 180  # clamp 到上限


# ---------------------------------------------------------------------------
# 发现层状态过滤：archived / deprecated / deleted 不进入运营聚合
# ---------------------------------------------------------------------------
async def _insert_lifecycle_event(db_session, *, asset_id, event_type, created_at=None):
    ev = AssetLifecycleEvent(
        asset_id=uuid.UUID(asset_id) if isinstance(asset_id, str) else asset_id,
        event_type=event_type, triggered_by="user",
    )
    if created_at is not None:
        ev.created_at = created_at
    db_session.add(ev)
    await db_session.commit()


async def test_archived_deprecated_excluded_from_indexing(client, db_session):
    """archived / deprecated 的 index_failed 资产不计入索引统计 / drilldown，只剩 active。"""
    active = await _insert_index_failed_asset(
        db_session, scope="company", project_id=None, owner=USER_BOSS,
        title="活跃失败资产", doc="wk-doc-active", asset_status="active",
    )
    await _insert_index_failed_asset(
        db_session, scope="company", project_id=None, owner=USER_BOSS,
        title="归档失败资产不可发现", doc="wk-doc-arch", asset_status="archived",
    )
    await _insert_index_failed_asset(
        db_session, scope="company", project_id=None, owner=USER_BOSS,
        title="弃用失败资产不可发现", doc="wk-doc-dep", asset_status="deprecated",
    )
    r = await client.get(INSIGHTS, headers=_hdr(USER_BOSS))
    assert r.status_code == 200, r.text
    body = r.json()
    # 只计 active 那条（治理范围内本测试构造的 company 失败资产）。
    assert body["indexing"]["index_failed"] == 1
    ids = {it["asset_id"] for it in body["recent_items"]}
    assert active in ids
    assert "归档失败资产不可发现" not in r.text
    assert "弃用失败资产不可发现" not in r.text
    _assert_no_leak(r.text)


async def test_original_access_stats_skip_undiscoverable_assets(client, db_session):
    """archived / deprecated 资产上的 pending 申请不计入 pending / overdue。"""
    # 启用超时规则，使 overdue 可计算。
    db_session.add(PermissionRule(
        rule_key="access_request_timeout_hours", rule_group="access_request", rule_type="numeric",
        display_name="访问申请自动通过时限", value_number=24, default_number=24, unit="小时", enabled=True,
    ))
    await db_session.commit()
    arch = await _insert_index_failed_asset(
        db_session, scope="company", project_id=None, owner=USER_BOSS,
        title="归档资产待审申请", doc="wk-doc-arch-req", asset_status="archived",
    )
    dep = await _insert_index_failed_asset(
        db_session, scope="company", project_id=None, owner=USER_BOSS,
        title="弃用资产待审申请", doc="wk-doc-dep-req", asset_status="deprecated",
    )
    # 两条都是 25h 前的 pending：若未过滤会进入 pending 且 overdue。
    await _insert_request(db_session, asset_id=uuid.UUID(arch), requester=USER_CONSULTANT, status="pending",
                          created_at=_now() - timedelta(hours=25))
    await _insert_request(db_session, asset_id=uuid.UUID(dep), requester=USER_CONSULTANT, status="pending",
                          created_at=_now() - timedelta(hours=25))
    r = await client.get(INSIGHTS, headers=_hdr(USER_BOSS))
    assert r.status_code == 200, r.text
    body = r.json()
    # 本测试未在可发现资产上建任何申请 → 计数应为 0。
    assert body["access"]["pending_original_requests"] == 0
    assert body["access"]["overdue_original_requests"] == 0
    assert "归档资产待审申请" not in r.text
    assert "弃用资产待审申请" not in r.text
    _assert_no_leak(r.text)


async def test_lifecycle_events_skip_undiscoverable_assets(client, db_session):
    """archived 资产上的旧 archive_candidate/warning 事件不污染当前洞察；active 资产仍统计。"""
    arch = await _insert_index_failed_asset(
        db_session, scope="company", project_id=None, owner=USER_BOSS,
        title="已归档资产旧事件", doc="wk-doc-arch-ev", asset_status="archived",
    )
    await _insert_lifecycle_event(db_session, asset_id=arch, event_type="archive_candidate")
    await _insert_lifecycle_event(db_session, asset_id=arch, event_type="archive_warning")

    active = await _insert_index_failed_asset(
        db_session, scope="company", project_id=None, owner=USER_BOSS,
        title="活跃资产候选事件", doc="wk-doc-active-ev", asset_status="active",
    )
    await _insert_lifecycle_event(db_session, asset_id=active, event_type="archive_candidate")
    await _insert_lifecycle_event(db_session, asset_id=active, event_type="archive_warning")

    r = await client.get(INSIGHTS, headers=_hdr(USER_BOSS))
    assert r.status_code == 200, r.text
    body = r.json()
    # 仅 active 资产的事件计入（按 distinct asset 计数）。
    assert body["lifecycle"]["archive_candidates"] == 1
    assert body["lifecycle"]["archive_warnings"] == 1
    assert "已归档资产旧事件" not in r.text
    _assert_no_leak(r.text)


async def test_needs_update_still_counted_and_discoverable(client, db_session):
    """needs_update 是 active-like 治理状态：lifecycle.needs_update 计数，且 index_failed 仍下钻。"""
    nu = await _insert_index_failed_asset(
        db_session, scope="company", project_id=None, owner=USER_BOSS,
        title="待更新失败资产", doc="wk-doc-nu", asset_status="needs_update",
    )
    r = await client.get(INSIGHTS, headers=_hdr(USER_BOSS))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["lifecycle"]["needs_update"] >= 1
    # needs_update 不在排除列表：其 index_failed active version 仍进入索引统计与 drilldown。
    assert body["indexing"]["index_failed"] >= 1
    ids = {it["asset_id"] for it in body["recent_items"]}
    assert nu in ids
    _assert_no_leak(r.text)

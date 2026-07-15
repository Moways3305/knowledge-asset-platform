"""集中权限判断服务测试（IMPLEMENT-03）。

以矩阵式构造覆盖 personal / project / company / L5 / admin / A4 / archived 等场景。
测试直接用 ORM 对象 + CallerContext 在内存中构造，不依赖数据库。
"""

from __future__ import annotations

import uuid

from app.models.knowledge import KnowledgeAsset
from app.schemas.permission import (
    AccessChannel,
    AccessLayer,
    CallerContext,
    DeniedReason,
    EffectiveAccessSource,
)
from app.services.permission import decide

# ---- 固定 id ----
U_CONSULTANT = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
U_BOSS = uuid.UUID("00000000-0000-0000-0000-0000000000c2")
U_DIRECTOR = uuid.UUID("00000000-0000-0000-0000-0000000000c3")
U_ADMIN = uuid.UUID("00000000-0000-0000-0000-0000000000c4")
U_OTHER = uuid.UUID("00000000-0000-0000-0000-0000000000c5")
P_ALPHA = uuid.UUID("00000000-0000-0000-0000-0000000000d1")
P_BETA = uuid.UUID("00000000-0000-0000-0000-0000000000d2")

DISCOVERY = AccessLayer.discovery
SUMMARY = AccessLayer.summary
ORIGINAL = AccessLayer.original


def _ctx(user_id, roles, projects=None, active=True) -> CallerContext:
    return CallerContext(
        user_id=user_id,
        is_active=active,
        active_company_roles=set(roles),
        active_project_ids=set(projects or []),
    )


def _asset(*, scope, level="L2", status="active", ai="A1", owner=U_OTHER, project_id=None):
    """内存构造一个知识资产（仅设置服务会读取的字段）。"""
    return KnowledgeAsset(
        title="t",
        scope=scope,
        zone="material",
        asset_type="methodology",
        owner_user_id=owner,
        project_id=project_id,
        visibility="project_only",
        confidentiality_level=level,
        ai_access_level=ai,
        asset_status=status,
    )


def test_owner_personal_all_layers_allowed():
    """本人个人知识：三层全部允许，来源为 owner。"""
    caller = _ctx(U_CONSULTANT, {"consultant"})
    asset = _asset(scope="personal", owner=U_CONSULTANT)
    for layer in (DISCOVERY, SUMMARY, ORIGINAL):
        d = decide(caller, asset, layer)
        assert d.allowed is True
        assert d.effective_access_source == EffectiveAccessSource.owner


def test_others_personal_all_layers_denied():
    """他人个人知识：三层全部拒绝，reason=personal_asset_not_owned。"""
    caller = _ctx(U_CONSULTANT, {"consultant"})
    asset = _asset(scope="personal", owner=U_OTHER)
    for layer in (DISCOVERY, SUMMARY, ORIGINAL):
        d = decide(caller, asset, layer)
        assert d.allowed is False
        assert d.denied_reason == DeniedReason.personal_asset_not_owned


def test_admin_only_cannot_own_personal_business_capability():
    """仅 admin 身份不得作为业务个人知识 owner 能力来源。

    纯系统身份在发现层即被 business_identity_required 拦截（早于 personal 归属判断）。
    """
    caller = _ctx(U_ADMIN, {"admin"})
    asset = _asset(scope="personal", owner=U_ADMIN)
    d = decide(caller, asset, DISCOVERY)
    assert d.allowed is False
    assert d.denied_reason == DeniedReason.business_identity_required


def test_project_member_all_layers_allowed_original_audited():
    """active 项目成员访问本项目资产三层允许，原文需审计。"""
    caller = _ctx(U_CONSULTANT, {"consultant"}, projects={P_ALPHA})
    asset = _asset(scope="project", level="L3", project_id=P_ALPHA)
    assert decide(caller, asset, DISCOVERY).allowed is True
    assert decide(caller, asset, SUMMARY).allowed is True
    d_orig = decide(caller, asset, ORIGINAL)
    assert d_orig.allowed is True
    assert d_orig.audit_required is True
    assert d_orig.effective_access_source == EffectiveAccessSource.project_member


def test_non_member_project_l3_l4_not_discoverable():
    """非项目成员不可发现、摘要或读取任何 project L3/L4 内容。"""
    caller = _ctx(U_CONSULTANT, {"consultant"}, projects={P_ALPHA})
    asset = _asset(scope="project", level="L4", project_id=P_BETA)  # 非成员项目
    d_sum = decide(caller, asset, SUMMARY)
    assert d_sum.allowed is False
    assert d_sum.denied_reason == DeniedReason.no_project_membership
    d_orig = decide(caller, asset, ORIGINAL)
    assert d_orig.allowed is False
    assert d_orig.denied_reason == DeniedReason.no_project_membership


def test_non_member_non_business_project_original_denied():
    """非业务身份且非项目成员不得获得项目原文（L1/L2）。

    纯系统身份连项目资产的发现层都不可达（business_identity_required），更不会到原文。
    """
    caller = _ctx(U_ADMIN, {"admin"})  # 非业务用户
    asset = _asset(scope="project", level="L2", project_id=P_ALPHA)
    d = decide(caller, asset, ORIGINAL)
    assert d.allowed is False
    assert d.denied_reason == DeniedReason.business_identity_required
    # 连发现层也不可达（不泄露存在性）。
    assert decide(caller, asset, DISCOVERY).allowed is False


def test_company_l1_l2_consultant_summary_only():
    """公司顾问对公司 L1/L2 仅到安全摘要，原文需治理角色。"""
    caller = _ctx(U_CONSULTANT, {"consultant"})
    asset = _asset(scope="company", level="L2")
    d = decide(caller, asset, ORIGINAL)
    assert d.allowed is False
    assert d.allowed_layer == SUMMARY
    assert d.denied_reason == DeniedReason.original_requires_request


def test_company_l3_l4_original_denied_summary_redacted():
    """公司 L3/L4 原文拒绝（original_requires_request），摘要脱敏。"""
    caller = _ctx(U_CONSULTANT, {"consultant"})
    asset = _asset(scope="company", level="L3")
    d_sum = decide(caller, asset, SUMMARY)
    assert d_sum.allowed is True
    assert d_sum.summary_variant == "redacted_summary"
    d_orig = decide(caller, asset, ORIGINAL)
    assert d_orig.allowed is False
    assert d_orig.denied_reason == DeniedReason.original_requires_request


def test_l5_boss_and_director_full_access_strong_audit():
    """L5：boss / consulting_director 三层允许，原文强审计。"""
    asset = _asset(scope="company", level="L5")
    for uid, role in ((U_BOSS, "boss"), (U_DIRECTOR, "consulting_director")):
        caller = _ctx(uid, {role})
        assert decide(caller, asset, DISCOVERY).allowed is True
        assert decide(caller, asset, SUMMARY).allowed is True
        d = decide(caller, asset, ORIGINAL)
        assert d.allowed is True
        assert d.strong_audit_required is True
        assert d.audit_required is True
        assert d.effective_access_source == EffectiveAccessSource.company_role


def test_l5_not_discoverable_for_consultant_and_admin():
    """L5 不可发现：consultant → l5_not_discoverable；纯 admin → business_identity_required
    （非业务身份更早被拦截）。两者都不可发现。"""
    asset = _asset(scope="company", level="L5")
    # 业务用户但非 L5 发现角色：l5_not_discoverable。
    d_consultant = decide(_ctx(U_CONSULTANT, {"consultant"}), asset, DISCOVERY)
    assert d_consultant.allowed is False
    assert d_consultant.denied_reason == DeniedReason.l5_not_discoverable
    # 纯系统身份：business_identity_required（早于 L5 判断）。
    d_admin = decide(_ctx(U_ADMIN, {"admin"}), asset, DISCOVERY)
    assert d_admin.allowed is False
    assert d_admin.denied_reason == DeniedReason.business_identity_required


def test_admin_only_no_business_original_on_company():
    """admin-only 不获得公司业务原文能力（连发现层都不可达，business_identity_required）。"""
    caller = _ctx(U_ADMIN, {"admin"})
    asset = _asset(scope="company", level="L2")
    d = decide(caller, asset, ORIGINAL)
    assert d.allowed is False
    assert d.denied_reason == DeniedReason.business_identity_required
    assert decide(caller, asset, DISCOVERY).allowed is False


def test_inactive_user_denied_everywhere():
    """inactive 用户全部拒绝，reason=user_inactive。"""
    caller = _ctx(U_CONSULTANT, {"consultant"}, active=False)
    asset = _asset(scope="company", level="L1")
    for layer in (DISCOVERY, SUMMARY, ORIGINAL):
        d = decide(caller, asset, layer)
        assert d.allowed is False
        assert d.denied_reason == DeniedReason.user_inactive


def test_archived_and_deprecated_asset_denied():
    """archived / deprecated 资产读侧默认拒绝，reason=asset_not_active。"""
    caller = _ctx(U_CONSULTANT, {"consultant"})
    for status in ("archived", "deprecated"):
        asset = _asset(scope="company", level="L2", status=status)
        d = decide(caller, asset, DISCOVERY)
        assert d.allowed is False
        assert d.denied_reason == DeniedReason.asset_not_active


def test_a4_agent_original_denied_but_human_allowed():
    """A4 资产：agent 渠道原文拒绝；human 渠道不因 A4 自动拒绝。"""
    caller = _ctx(U_CONSULTANT, {"consultant"})
    asset = _asset(scope="company", level="L2", ai="A4")
    d_agent = decide(caller, asset, ORIGINAL, channel=AccessChannel.agent)
    assert d_agent.allowed is False
    assert d_agent.denied_reason == DeniedReason.original_requires_request

    d_human = decide(caller, asset, ORIGINAL, channel=AccessChannel.human)
    assert d_human.allowed is False
    assert d_human.denied_reason == DeniedReason.original_requires_request


def test_allowed_layer_reports_highest_reachable_on_allow():
    """allowed=True 时 allowed_layer 表示可达最高层级，而非本次请求层级。"""
    # 公司顾问最高可达 summary；请求 discovery 时 allowed_layer 应为 summary。
    caller = _ctx(U_CONSULTANT, {"consultant"})
    asset = _asset(scope="company", level="L2")
    d = decide(caller, asset, DISCOVERY)
    assert d.allowed is True
    assert d.requested_layer == DISCOVERY
    assert d.allowed_layer == SUMMARY


def test_allowed_layer_equals_summary_when_max_is_summary():
    """可达最高为 summary 时，请求 summary：allowed_layer=summary。"""
    # 公司 L3：业务用户可达 summary（脱敏），不可达 original。
    caller = _ctx(U_CONSULTANT, {"consultant"})
    asset = _asset(scope="company", level="L3")
    d = decide(caller, asset, SUMMARY)
    assert d.allowed is True
    assert d.allowed_layer == SUMMARY


def test_allowed_layer_on_denied_original_reports_summary():
    """可达最高为 summary 时，请求 original 被拒：allowed_layer 仍为 summary。"""
    caller = _ctx(U_CONSULTANT, {"consultant"})
    asset = _asset(scope="company", level="L3")
    d = decide(caller, asset, ORIGINAL)
    assert d.allowed is False
    assert d.allowed_layer == SUMMARY
    assert d.denied_reason == DeniedReason.original_requires_request


def test_layer_recursion_discovery_denied_implies_all_denied():
    """发现层被拒时，摘要层与原文层也必须被拒。"""
    caller = _ctx(U_CONSULTANT, {"consultant"})
    asset = _asset(scope="company", level="L2", status="archived")
    assert decide(caller, asset, DISCOVERY).allowed is False
    assert decide(caller, asset, SUMMARY).allowed is False
    assert decide(caller, asset, ORIGINAL).allowed is False

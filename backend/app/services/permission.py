"""集中权限判断服务。

把权限模型中知识资产的三层访问判断收口到这里，供各 API 复用。
**所有权限业务判断只能放在本模块**，不得在 API / 测试 / 其它模块散落。

原文授权运行时联动：
- 跨项目 / 公司 L3/L4 原文默认按"需要申请"（original_requires_request）；审批通过的
  active access_grant 经 `decide(..., has_original_grant=True)` 在运行时放行原文层
  （source=access_grant，需审计），过期 / 撤销立即失效。
- L1/L2 原文默认策略集中在 `DefaultAccessPolicy`（schemas.permission）。**已规则化**
  ——业务读路径调 `permission_rules.load_access_policy(session)` 把 `permission_rules` 的
  `cross_project_l1_l2_original_for_business_user` / `company_l1_l2_original_for_business_user`
  开关注入 `decide(policy=...)`；`decide()` 仍是纯函数（默认 `DEFAULT_POLICY`，便于单测）。
- A4 的原文边界仅对 access_channel=agent 生效（human 不因 A4 自动拒绝），授权不绕过 A4。
- archived / deprecated 资产读侧默认不可发现（asset_not_active）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from sqlalchemy import and_, false, or_, true
from sqlalchemy.sql.elements import ColumnElement

from app.models.identity import User
from app.models.knowledge import KnowledgeAsset
from app.schemas.enums import (
    AiAccessLevel,
    AssetStatus,
    ConfidentialityLevel,
    KnowledgeScope,
    MemberStatus,
    ProjectRole,
    RoleStatus,
    SummaryType,
)
from app.schemas.permission import (
    DEFAULT_POLICY,
    AccessChannel,
    AccessLayer,
    CallerContext,
    DefaultAccessPolicy,
    DeniedReason,
    EffectiveAccessSource,
    PermissionDecision,
    layer_rank,
)
from app.services.work_identity import default_active_role

# 读侧默认不可进入检索/访问的资产状态。
_INACTIVE_ASSET_STATUSES = {
    # Internal approval/indexing state. It must never enter discovery, summary,
    # original preview, or agent paths before the approval closes successfully.
    "processing",
    AssetStatus.archived.value,
    AssetStatus.deprecated.value,
    # deleted：软删除态全程不可发现 / 摘要 / 原文（含 access_grant 也不放行）。
    AssetStatus.deleted.value,
}
# 需要脱敏摘要的保密级别。
_REDACTED_SUMMARY_LEVELS = {ConfidentialityLevel.L3.value, ConfidentialityLevel.L4.value}

_logger = logging.getLogger(__name__)


def build_caller_context(user: User, *, active_company_role: str | None = None) -> CallerContext:
    """从 User（需已加载 company_roles / project_members）构建调用人上下文。

    只统计 active 的公司角色与项目成员关系。项目成员关系始终加载，不随当前
    active 公司角色变化，以便在项目层面使用户的项目角色（如 project_manager）
    被正确识别；公司业务相关属性（is_business_user / can_discover_l5）仍由
    active 公司角色决定。
    """
    assigned_roles = {
        r.company_role for r in user.company_roles if r.status == RoleStatus.active.value
    }
    selected_role = active_company_role or default_active_role(user)
    active_roles = {selected_role} if selected_role in assigned_roles else set()
    active_members = [m for m in user.project_members if m.status == MemberStatus.active.value]
    active_projects = {m.project_id for m in active_members}
    active_project_roles = {m.project_id: m.project_role for m in active_members}
    return CallerContext(
        user_id=user.id,
        is_active=user.status == "active",
        active_company_roles=active_roles,
        active_project_ids=active_projects,
        active_project_roles=active_project_roles,
    )


@dataclass(frozen=True)
class _AccessProfile:
    """调用人在某资产上的"可达画像"。

    max_layer：可达到的最高层级（None=连发现层都不可）。
    exceed_reason：当请求层级超过 max_layer 时返回的拒绝原因。
    source：放行来源（用于 allowed 时的 effective_access_source）。
    original_audit_required / original_strong_audit_required：原文层是否需审计/强审计。
    summary_variant：摘要层提示（L3/L4 → redacted_summary）。
    """

    max_layer: AccessLayer | None
    exceed_reason: DeniedReason
    source: EffectiveAccessSource
    original_audit_required: bool = False
    original_strong_audit_required: bool = False
    summary_variant: str | None = None


def _profile_none(reason: DeniedReason) -> _AccessProfile:
    """构造"连发现层都不可"的画像。"""
    return _AccessProfile(max_layer=None, exceed_reason=reason, source=EffectiveAccessSource.none)


def _base_profile(
    caller: CallerContext, asset: KnowledgeAsset, policy: DefaultAccessPolicy
) -> _AccessProfile:
    """计算调用人在该资产上的可达画像（不含 A4/agent 的渠道判断、不含 access_grant 放大）。

    判断顺序刻意如此，避免信息泄露：
    1. inactive 用户全部拒绝；
    2. 纯系统身份（非业务用户，如仅 admin）不浏览任何业务知识内容（发现/摘要/原文全拒）；
    3. personal：非本人（或本人但非业务用户）一律 personal_asset_not_owned，不泄露；
    4. 非 personal 的 L5：非总经理/咨询总监 l5_not_discoverable（连存在信息都不给）；
    5. archived/deprecated 读侧默认不可发现（asset_not_active）；
    6. 其余按 scope + 保密级别给出可达层级。
    """
    if not caller.is_active:
        return _profile_none(DeniedReason.user_inactive)

    # 纯系统身份（admin 等非业务用户）不是业务身份，不经知识发现路径浏览任何
    # 业务知识（个人/项目/公司，含发现/摘要/原文）。admin 的运营可见性走专门的 admin
    # 元数据接口（入库/扫描/审计），那些接口只回安全运营元数据、不含业务正文/摘要全文。
    # fail-closed：连资产是否存在都不泄露（detail 统一 404）。
    if not caller.is_business_user:
        return _profile_none(DeniedReason.business_identity_required)

    scope = asset.scope
    level = asset.confidentiality_level

    # ---- personal：个人知识库 ----
    if scope == KnowledgeScope.personal.value:
        is_owner_business = asset.owner_user_id == caller.user_id and caller.is_business_user
        if not is_owner_business:
            # 他人个人知识、或仅 admin 身份"拥有"的个人知识，都不可发现。
            return _profile_none(DeniedReason.personal_asset_not_owned)
        if asset.asset_status in _INACTIVE_ASSET_STATUSES:
            return _profile_none(DeniedReason.asset_not_active)
        # 本人业务用户：三层全开，本人访问自有知识不强制审计。
        return _AccessProfile(
            max_layer=AccessLayer.original,
            exceed_reason=DeniedReason.allowed,
            source=EffectiveAccessSource.owner,
        )

    # 公司层角色不产生项目成员关系。所有项目知识先校验 active project_members，
    # 再进入保密等级判定；治理角色也不能跨项目绕过。
    if scope == KnowledgeScope.project.value and asset.project_id not in caller.active_project_ids:
        return _profile_none(DeniedReason.no_project_membership)

    # ---- 非 personal 的 L5：发现需总经理/咨询总监 ----
    if level == ConfidentialityLevel.L5.value:
        if not caller.can_discover_l5:
            return _profile_none(DeniedReason.l5_not_discoverable)
        if asset.asset_status in _INACTIVE_ASSET_STATUSES:
            return _profile_none(DeniedReason.asset_not_active)
        # 总经理 / 咨询总监：原文需强审计，来源为公司角色。
        return _AccessProfile(
            max_layer=AccessLayer.original,
            exceed_reason=DeniedReason.allowed,
            source=EffectiveAccessSource.company_role,
            original_audit_required=True,
            original_strong_audit_required=True,
        )

    # ---- 非 L5 的 project / company：先做读侧状态过滤 ----
    if asset.asset_status in _INACTIVE_ASSET_STATUSES:
        return _profile_none(DeniedReason.asset_not_active)

    summary_variant = (
        SummaryType.redacted_summary.value if level in _REDACTED_SUMMARY_LEVELS else None
    )

    if scope == KnowledgeScope.project.value:
        # 已在上方完成 active 成员校验；项目角色与公司职务分别存储，成员公司角色不影响读取。
        return _AccessProfile(
            max_layer=AccessLayer.original,
            exceed_reason=DeniedReason.allowed,
            source=EffectiveAccessSource.project_member,
            original_audit_required=True,
        )

    if scope == KnowledgeScope.company.value:
        # 公司知识：治理角色默认可访问原文；顾问只到安全摘要。L5 已在上方保持原有强边界。
        if caller.can_discover_l5:
            return _AccessProfile(
                max_layer=AccessLayer.original,
                exceed_reason=DeniedReason.allowed,
                source=EffectiveAccessSource.company_role,
                original_audit_required=True,
            )
        return _AccessProfile(
            max_layer=AccessLayer.summary,
            exceed_reason=DeniedReason.original_requires_request,
            source=EffectiveAccessSource.system_rule,
            summary_variant=summary_variant,
        )

    # 兜底：未知 scope，保守拒绝。
    return _profile_none(DeniedReason.original_requires_request)


def _build_profile(
    caller: CallerContext,
    asset: KnowledgeAsset,
    policy: DefaultAccessPolicy,
    has_original_grant: bool = False,
) -> _AccessProfile:
    """在基础画像上叠加 access_grant 原文放大。

    `has_original_grant`（调用人对本资产有 active access_grant 原文授权）只在画像
    「可发现但原文受限」（max_layer=summary，即跨项目/公司 L3/L4、L1/L2 默认未放行等
    `original_requires_request` / `no_project_membership` 软拒绝）时把原文层放行
    （source=access_grant，需审计）。它**不**放大 L5 发现 / 他人个人 / inactive /
    archived（这些 max_layer=None，不予提升）；也**不**绕过 A4-agent（A4 边界在
    `decide()` 放行之后再判，授权不绕过）。
    """
    profile = _base_profile(caller, asset, policy)
    if has_original_grant and profile.max_layer == AccessLayer.summary:
        return replace(
            profile,
            max_layer=AccessLayer.original,
            exceed_reason=DeniedReason.allowed,
            source=EffectiveAccessSource.access_grant,
            original_audit_required=True,
        )
    return profile


def decide(
    caller: CallerContext,
    asset: KnowledgeAsset,
    layer: AccessLayer,
    *,
    channel: AccessChannel = AccessChannel.human,
    policy: DefaultAccessPolicy = DEFAULT_POLICY,
    has_original_grant: bool = False,
) -> PermissionDecision:
    """对"调用人 + 资产 + 请求层级 + 渠道"作出权限决策。

    三层递进：请求层级 <= 可达最高层级才允许；发现层被拒则摘要/原文必拒。
    A4 边界：access_channel=agent 请求 original 且资产 ai_access_level=A4 时拒绝。
    `has_original_grant` 由调用方按 active access_grants 查得后传入（运行时联动）。
    """
    profile = _build_profile(caller, asset, policy, has_original_grant)
    max_rank = layer_rank(profile.max_layer)
    req_rank = layer_rank(layer)

    # 摘要层提示只在请求摘要层时附带（L3/L4 → 脱敏摘要）。
    summary_variant = profile.summary_variant if layer == AccessLayer.summary else None

    allowed = max_rank > 0 and req_rank <= max_rank

    if allowed:
        # A4 原文边界：仅对 agent 渠道的原文请求生效（human 不因 A4 自动拒绝）。
        if (
            layer == AccessLayer.original
            and channel == AccessChannel.agent
            and asset.ai_access_level == AiAccessLevel.A4.value
        ):
            return PermissionDecision(
                allowed=False,
                requested_layer=layer,
                allowed_layer=profile.max_layer,
                denied_reason=DeniedReason.agent_a4_original_denied,
                effective_access_source=EffectiveAccessSource.none,
                audit_required=False,
                strong_audit_required=False,
                summary_variant=None,
            )
        is_original = layer == AccessLayer.original
        # DEBUG：仅记 layer / source 等枚举（无业务正文 / 标题）。
        _logger.debug(
            "permission_decision",
            extra={
                "allowed": True,
                "requested_layer": layer.value,
                "allowed_layer": profile.max_layer.value if profile.max_layer else None,
                "source": profile.source.value,
            },
        )
        return PermissionDecision(
            allowed=True,
            requested_layer=layer,
            # allowed_layer 始终表示"可达最高层级"，而非本次请求层级。
            allowed_layer=profile.max_layer,
            denied_reason=DeniedReason.allowed,
            effective_access_source=profile.source,
            audit_required=profile.original_audit_required if is_original else False,
            strong_audit_required=(
                profile.original_strong_audit_required if is_original else False
            ),
            summary_variant=summary_variant,
        )

    # 被拒：allowed_layer 表示可达最高层级（便于调用方理解差距）。
    _logger.debug(
        "permission_decision",
        extra={
            "allowed": False,
            "requested_layer": layer.value,
            "denied_reason": profile.exceed_reason.value,
        },
    )
    return PermissionDecision(
        allowed=False,
        requested_layer=layer,
        allowed_layer=profile.max_layer,
        denied_reason=profile.exceed_reason,
        effective_access_source=EffectiveAccessSource.none,
        audit_required=False,
        strong_audit_required=False,
        summary_variant=summary_variant,
    )


def discovery_filter(caller: CallerContext) -> ColumnElement[bool]:
    """Return the SQL predicate equivalent of ``decide(..., discovery)``.

    List/count queries must apply this predicate before pagination so totals never
    reveal assets outside the caller's discovery boundary. ``decide`` remains the
    authoritative per-asset decision and is still used while projecting DTOs.
    """
    if not caller.is_active or not caller.is_business_user:
        return false()

    active = KnowledgeAsset.asset_status.notin_(_INACTIVE_ASSET_STATUSES)
    personal = and_(
        KnowledgeAsset.scope == KnowledgeScope.personal.value,
        KnowledgeAsset.owner_user_id == caller.user_id,
    )

    l5_visible = (
        KnowledgeAsset.confidentiality_level != ConfidentialityLevel.L5.value
        if not caller.can_discover_l5
        else true()
    )
    company = and_(KnowledgeAsset.scope == KnowledgeScope.company.value, l5_visible)
    project = and_(
        KnowledgeAsset.scope == KnowledgeScope.project.value,
        KnowledgeAsset.project_id.in_(caller.active_project_ids),
        l5_visible,
    )
    return and_(active, or_(personal, project, company))


# ============================================================
# 生命周期治理动作的权限判断
# 这些判断同样收口在本模块，服务层不得另写权限矩阵。
# 注意：生命周期动作要在 archived 资产上也成立（重新启用），因此【不复用】
# decide()（其对 archived 作 asset_not_active 发现层拒绝），而是给出独立的
# 「可见性（防泄露）」与「动作授权（按 scope 治理角色）」两段判断。
# ============================================================


def lifecycle_visibility(caller: CallerContext, asset: KnowledgeAsset) -> DeniedReason | None:
    """生命周期可见性（防泄露）。返回 None 表示调用人可“看见”该资产以进行治理；
    否则返回安全拒绝原因（与发现层一致：他人个人 / 无权 L5 一律表现为不存在）。

    与 decide(discovery) 的区别：此处【不】因 archived/deprecated 而拒绝——治理
    动作（尤其重新启用）必须能作用于已归档资产。
    """
    if not caller.is_active:
        return DeniedReason.user_inactive
    if asset.scope == KnowledgeScope.personal.value:
        is_owner_business = asset.owner_user_id == caller.user_id and caller.is_business_user
        return None if is_owner_business else DeniedReason.personal_asset_not_owned
    if asset.confidentiality_level == ConfidentialityLevel.L5.value and not caller.can_discover_l5:
        return DeniedReason.l5_not_discoverable
    return None


def lifecycle_actor_allowed(caller: CallerContext, asset: KnowledgeAsset) -> bool:
    """按 scope 判断调用人是否为合法的生命周期治理动作人（发起/确认）。

    - personal：知识所有者本人。
    - project：资产 maintainer 或该项目 active project_manager。
    - company：boss / consulting_director（治理角色）。

    前置：调用方需先确保 caller.is_business_user（纯 admin 由服务层独立拒绝并强审计）。
    """
    scope = asset.scope
    if scope == KnowledgeScope.personal.value:
        return asset.owner_user_id == caller.user_id and caller.is_business_user
    if scope == KnowledgeScope.project.value:
        if asset.maintainer_user_id == caller.user_id:
            return True
        return (
            asset.project_id is not None
            and caller.active_project_roles.get(asset.project_id)
            == ProjectRole.project_manager.value
        )
    if scope == KnowledgeScope.company.value:
        return caller.can_discover_l5  # boss / consulting_director
    return False


def lifecycle_is_strong_audit(asset: KnowledgeAsset) -> bool:
    """L5 / A4 / 公司级资产的归档确认与重新启用确认需强审计（severity + risk_level）。"""
    return (
        asset.confidentiality_level == ConfidentialityLevel.L5.value
        or asset.ai_access_level == AiAccessLevel.A4.value
        or asset.scope == KnowledgeScope.company.value
    )

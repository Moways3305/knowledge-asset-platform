"""权限判断相关的结构化类型。

集中定义三层访问的枚举、调用人上下文（CallerContext）、权限决策结果
（PermissionDecision），以及 L1/L2 原文默认策略对象（DefaultAccessPolicy）。

枚举值（key）使用英文技术 key；以 str Enum 表达，传输/存储为字符串，
不做 DB enum。所有判断逻辑在 `app/services/permission.py`，本模块只放类型。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel

from app.schemas.enums import BUSINESS_COMPANY_ROLES, L5_DISCOVERY_ROLES


class AccessLayer(str, Enum):
    """三层访问，敏感度递增：discovery < summary < original。"""

    discovery = "discovery"
    summary = "summary"
    original = "original"


# 三层访问的等级排序，用于"递进"判断（被拒的下层导致上层也被拒）。
_LAYER_RANK: dict[AccessLayer, int] = {
    AccessLayer.discovery: 1,
    AccessLayer.summary: 2,
    AccessLayer.original: 3,
}


def layer_rank(layer: AccessLayer | None) -> int:
    """返回访问层级的等级；None 表示连发现层都不允许，等级为 0。"""
    if layer is None:
        return 0
    return _LAYER_RANK[layer]


class AccessChannel(str, Enum):
    """访问渠道。human 为人工访问；agent 为 Agent 调用（A4 原文边界对 agent 生效）。"""

    human = "human"
    agent = "agent"


class DeniedReason(str, Enum):
    """权限拒绝原因（三层访问判断的拒绝原因子集 + 读侧状态过滤）。"""

    allowed = "allowed"  # 未拒绝（allowed=True 时使用）
    user_inactive = "user_inactive"
    personal_asset_not_owned = "personal_asset_not_owned"
    l5_not_discoverable = "l5_not_discoverable"
    no_project_membership = "no_project_membership"
    original_requires_request = "original_requires_request"
    agent_a4_original_denied = "agent_a4_original_denied"
    asset_not_active = "asset_not_active"  # 读侧默认过滤：archived/deprecated
    # 纯系统身份（非业务用户，如仅 admin）不浏览任何业务知识内容。
    business_identity_required = "business_identity_required"


class EffectiveAccessSource(str, Enum):
    """有效访问来源。"""

    owner = "owner"  # 本人个人知识
    project_member = "project_member"  # 所在项目成员
    company_role = "company_role"  # 公司角色（如 L5 → boss/consulting_director）
    system_rule = "system_rule"  # 由默认/平台规则放行（L1/L2、公司发现/摘要等）
    access_grant = "access_grant"  # 由有效 access_grants 原文授权放行
    none = "none"  # 未放行


class CallerContext(BaseModel):
    """调用人上下文（从身份信息派生的判断输入）。

    is_business_user / can_discover_l5 由 active 公司角色推导；admin 不在业务集合
    与 L5 集合内，因此仅 admin 身份不会让二者为真。
    """

    user_id: uuid.UUID
    is_active: bool
    active_company_roles: set[str]
    active_project_ids: set[uuid.UUID]
    # 每个 active 项目的项目角色（project_id → project_role）。同一用户同一项目至多
    # 一条成员关系，故每项目一个角色。用于生命周期等需要项目角色的治理判断，
    # 避免在服务层散查 ProjectMember。
    active_project_roles: dict[uuid.UUID, str] = {}

    @property
    def active_company_role(self) -> str | None:
        return (
            next(iter(self.active_company_roles)) if len(self.active_company_roles) == 1 else None
        )

    @property
    def is_business_user(self) -> bool:
        return any(r in BUSINESS_COMPANY_ROLES for r in self.active_company_roles)

    @property
    def can_discover_l5(self) -> bool:
        return any(r in L5_DISCOVERY_ROLES for r in self.active_company_roles)


class PermissionDecision(BaseModel):
    """单次权限判断结果（结构化 decision）。"""

    allowed: bool
    requested_layer: AccessLayer
    # 调用人在该资产上可达到的最高层级（None 表示连发现层都不可）。
    allowed_layer: AccessLayer | None
    denied_reason: DeniedReason
    effective_access_source: EffectiveAccessSource
    audit_required: bool
    strong_audit_required: bool
    # 摘要层提示：L3/L4 对外摘要只允许脱敏摘要（redacted_summary）。
    summary_variant: str | None = None


@dataclass(frozen=True)
class DefaultAccessPolicy:
    """公司 L1/L2 原文默认放行策略。

    跨项目项目知识 L1-L4 与公司知识 L3/L4 原文默认按"需要申请"
    （original_requires_request）；审批通过的 active access_grant 会在运行时把对应
    资产的原文层放行（见 permission.decide 的 has_original_grant）。本对象只承载公司
    L1/L2 默认放行开关，其运行时值由 permission_rules 集中提供。
    """

    # 公司知识 L1/L2 原文：默认放行给 active 业务用户。
    company_l1_l2_original_for_business_user: bool = True


# 平台默认策略实例。后续可由 permission_rules 加载结果替换。
DEFAULT_POLICY = DefaultAccessPolicy()

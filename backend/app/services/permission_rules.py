"""权限规则配置中心服务。

`permission_rules` 的幂等默认 seed、读取、更新。权限治理规则是**配置中心**：
阈值 / 开关 / 固定路径三类配置项落库、可读写、写操作审计。

权限边界（后端权威）：
- 读：admin / boss / consulting_director。consultant → 403。
- 写：仅 boss / consulting_director（业务治理角色）。
  - admin 写 → 403，denied_reason=admin_business_permission_denied（admin 是系统身份，
    不因此获得业务权限规则的修改权）。
  - consultant 写 → 403（无读权，自然无写权）。
- fixed_path 规则不可修改（422）。

边界提醒：
- 本服务**不**实现 access_grants / original_access_requests / 原文授权撤销。
- 本服务**不**改生命周期扫描运行时来源（归档阈值的运行时来源仍是 alert_rules）；
  permission_rules 中的归档相关项只作治理配置视图，不驱动 lifecycle scan，避免回归。
- 响应 / 审计**绝不**含 token / secret / provider 内部标识 / 存储引用 / 业务原文。
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import User
from app.models.permission_rule import PermissionRule
from app.schemas.enums import AuditAction, AuditLogType, CompanyRole
from app.schemas.permission import DEFAULT_POLICY, CallerContext, DefaultAccessPolicy
from app.schemas.permission_rule import (
    PermissionRuleOut,
    PermissionRulesResponse,
    PermissionRuleUpdateRequest,
)
from app.services import audit as audit_service

# 规则类型常量。
RULE_NUMERIC = "numeric"
RULE_TOGGLE = "toggle"
RULE_FIXED_PATH = "fixed_path"

# 规则分组常量（与前端展示分组一致）。
GROUP_PERSONAL = "personal_flow"
GROUP_UPGRADE = "project_upgrade"
GROUP_ACCESS = "access_request"
GROUP_LIFECYCLE = "asset_lifecycle"


def _num(key, group, name, value, unit, desc):
    return {
        "rule_key": key,
        "rule_group": group,
        "rule_type": RULE_NUMERIC,
        "display_name": name,
        "value_number": float(value),
        "unit": unit,
        "description": desc,
        "editable": True,
    }


def _toggle(key, group, name, value, desc):
    return {
        "rule_key": key,
        "rule_group": group,
        "rule_type": RULE_TOGGLE,
        "display_name": name,
        "value_bool": bool(value),
        "unit": None,
        "description": desc,
        "editable": True,
    }


def _fixed(key, group, name, text, unit, desc):
    return {
        "rule_key": key,
        "rule_group": group,
        "rule_type": RULE_FIXED_PATH,
        "display_name": name,
        "value_text": text,
        "unit": unit,
        "description": desc,
        "editable": False,
    }


# 默认规则（幂等 seed；覆盖前端与 README 展示的全部 rule_key）。
# 说明：归档相关阈值（asset_archive_*）此处仅作治理配置视图，运行时来源仍为 alert_rules
# （lifecycle scan 不读本表），不改其运行时行为。
DEFAULT_RULES: list[dict] = [
    # ---- 个人知识流转 ----
    _toggle(
        "personal_knowledge_default_private",
        GROUP_PERSONAL,
        "个人知识默认私密",
        True,
        "个人知识不参与他人检索，仅本人可用；其他顾问 / 项目经理 / 公司级检索均不命中他人个人知识",
    ),
    _toggle(
        "personal_to_project_material_requires_owner_submit",
        GROUP_PERSONAL,
        "个人提交项目资料需本人确认",
        True,
        "个人知识进入项目资料区必须由本人主动提交，项目经理或其他顾问不能代为操作",
    ),
    _fixed(
        "project_asset_validation_paths",
        GROUP_PERSONAL,
        "项目资产确认路径",
        "内部分享 / 客户验证",
        "条路径",
        "项目资产必须至少经过一条验证路径（内部分享或客户验证），并由项目经理确认后标记为资产区（zone = asset）",
    ),
    # ---- 项目知识升格 ----
    _num(
        "cross_project_source_threshold",
        GROUP_UPGRADE,
        "跨项目来源阈值",
        3,
        "个项目",
        "项目知识被至少 N 个不同项目调用，表示具备跨项目复用广度",
    ),
    _num(
        "cross_project_call_count_threshold",
        GROUP_UPGRADE,
        "跨项目调用次数阈值",
        10,
        "次",
        "项目知识累计跨项目调用达到 N 次，表示具备复用强度；需与跨项目来源阈值共同判断",
    ),
    _num(
        "project_upgrade_signal_window_days",
        GROUP_UPGRADE,
        "升格信号统计窗口",
        90,
        "天",
        "仅统计最近 N 天内的跨项目来源与调用次数，避免历史噪声",
    ),
    _num(
        "review_timeout_hours",
        GROUP_UPGRADE,
        "升格审核超时",
        48,
        "小时",
        "升格审核提交后超过此时间未处理，系统发送催审通知",
    ),
    # ---- 访问申请 ----
    _num(
        "access_request_timeout_hours",
        GROUP_ACCESS,
        "访问申请自动通过时限",
        24,
        "小时",
        "访问申请超过此时间未审批，由后台任务自动通过并生成授权。"
        "仅对 L1/L2 资产生效，L3/L4/L5 机密资产不自动通过；禁用 / 值 ≤0 则不自动通过",
    ),
    _num(
        "access_grant_duration_days",
        GROUP_ACCESS,
        "授权有效期",
        7,
        "天",
        "访问授权到期后需重新申请，防止无限期访问",
    ),
    # L1/L2 默认原文放行。
    _toggle(
        "cross_project_l1_l2_original_for_business_user",
        GROUP_ACCESS,
        "跨项目 L1/L2 原文默认放行业务用户",
        True,
        "业务用户访问其它项目 L1/L2 原文是否默认放行。"
        "关闭后非本项目成员对其它项目 L1/L2 最多到摘要层，原文需申请授权",
    ),
    _toggle(
        "company_l1_l2_original_for_business_user",
        GROUP_ACCESS,
        "公司 L1/L2 原文默认放行业务用户",
        True,
        "业务用户访问公司库 L1/L2 原文是否默认放行。"
        "关闭后普通业务用户对公司 L1/L2 最多到摘要层，原文需申请授权",
    ),
    # ---- 资产生命周期 ----
    _num(
        "asset_modify_rate_threshold",
        GROUP_LIFECYCLE,
        "高修改率预警阈值",
        30,
        "%",
        "资产入库后修改率超过此值，触发质量复核建议",
    ),
    _num(
        "asset_not_helpful_threshold",
        GROUP_LIFECYCLE,
        "负反馈预警阈值",
        3,
        "次",
        "资产收到「无帮助」反馈达到此次数，标记为待复核",
    ),
    _num(
        "asset_expiry_days",
        GROUP_LIFECYCLE,
        "资产有效期",
        365,
        "天",
        "资产超过有效期未更新，触发过期提醒与归档建议",
    ),
    _num(
        "asset_archive_inactive_days",
        GROUP_LIFECYCLE,
        "归档不活跃阈值",
        730,
        "天",
        "资产超过此天数未被调用，进入归档候选。运行时归档扫描阈值以 alert_rules 为准，本项为治理配置视图",
    ),
    _num(
        "asset_archive_notice_days",
        GROUP_LIFECYCLE,
        "归档预警提前天数",
        30,
        "天",
        "资产距离自动归档还剩此天数时，向维护人发送归档预警。运行时来源为 alert_rules，本项为治理配置视图",
    ),
]

# 分组显示顺序（与前端一致）。
GROUP_ORDER = [GROUP_PERSONAL, GROUP_UPGRADE, GROUP_ACCESS, GROUP_LIFECYCLE]
_GROUP_RANK = {g: i for i, g in enumerate(GROUP_ORDER)}


# ---------------------------------------------------------------------------
# 运行时读取：把已有 permission_rules 接入真实权限运行时。
# 收口在本服务，业务读路径只调 load_access_policy()，不散落读规则。
# ---------------------------------------------------------------------------
_RUNTIME_TOGGLE_KEYS = (
    "cross_project_l1_l2_original_for_business_user",
    "company_l1_l2_original_for_business_user",
)
_TIMEOUT_RULE_KEY = "access_request_timeout_hours"


def _runtime_toggle(rule: PermissionRule | None, *, default: bool) -> bool:
    """运行时取 toggle 值：

    - 缺失 → `default`（出厂默认；规则尚未 seed 时不全锁死，保持当前行为）。
    - 禁用 / 非 toggle 类型 / value_bool 为空 → **False**（治理端禁用 / 取值非法即视为关闭，
      绝不回到 True 默认——否则禁用规则没有效果）。
    """
    if rule is None:
        return default
    if not rule.enabled or rule.rule_type != RULE_TOGGLE or rule.value_bool is None:
        return False
    return bool(rule.value_bool)


async def load_access_policy(session: AsyncSession) -> DefaultAccessPolicy:
    """从 permission_rules 读取 L1/L2 原文默认放行开关，构建运行时 DefaultAccessPolicy。

    供所有业务读路径在调用 `decide()` 前注入；规则缺失回退出厂默认，禁用/非法 fail-closed。
    """
    rows = (
        (
            await session.execute(
                select(PermissionRule).where(PermissionRule.rule_key.in_(_RUNTIME_TOGGLE_KEYS))
            )
        )
        .scalars()
        .all()
    )
    by_key = {r.rule_key: r for r in rows}
    return DefaultAccessPolicy(
        cross_project_l1_l2_original_for_business_user=_runtime_toggle(
            by_key.get("cross_project_l1_l2_original_for_business_user"),
            default=DEFAULT_POLICY.cross_project_l1_l2_original_for_business_user,
        ),
        company_l1_l2_original_for_business_user=_runtime_toggle(
            by_key.get("company_l1_l2_original_for_business_user"),
            default=DEFAULT_POLICY.company_l1_l2_original_for_business_user,
        ),
    )


async def access_request_timeout_hours(session: AsyncSession) -> float | None:
    """原文访问申请自动审批的超时小时数。

    仅当规则存在、enabled、numeric、value_number > 0 时返回该值；否则 → None（不自动审批）。
    缺失 / 禁用 / 非 numeric / 值非法 / <=0 一律 None，保守不自动放行。
    """
    rule = (
        await session.execute(
            select(PermissionRule).where(PermissionRule.rule_key == _TIMEOUT_RULE_KEY)
        )
    ).scalar_one_or_none()
    if rule is None or not rule.enabled or rule.rule_type != RULE_NUMERIC:
        return None
    try:
        hours = float(rule.value_number) if rule.value_number is not None else 0.0
    except (TypeError, ValueError):
        return None
    return hours if hours > 0 else None


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"denied_reason": reason, "message": message}
    )


def _is_admin(caller: CallerContext) -> bool:
    return CompanyRole.admin.value in caller.active_company_roles


def _is_governance(caller: CallerContext) -> bool:
    # 业务治理角色 = boss / consulting_director（与可发现 L5 一致）。
    return caller.can_discover_l5


def _require_read(caller: CallerContext) -> None:
    """读权限规则：admin 或治理角色。consultant / 其它 → 403。"""
    if not (_is_admin(caller) or _is_governance(caller)):
        raise _denied(
            403, "permission_rules_forbidden", "无权限规则查看权（仅 admin / 总经理 / 咨询总监）"
        )


def _require_write(caller: CallerContext) -> None:
    """写权限规则：仅业务治理角色。admin 只读 → 403。consultant → 403。"""
    if _is_governance(caller):
        return
    if _is_admin(caller):
        # admin 是系统身份，不因此获得业务权限规则修改权（与权限模型边界一致）。
        raise _denied(
            403,
            "admin_business_permission_denied",
            "admin 不可修改业务权限规则（仅总经理 / 咨询总监）",
        )
    raise _denied(403, "permission_rules_forbidden", "无权限规则修改权（仅总经理 / 咨询总监）")


async def ensure_default_rules(session: AsyncSession) -> None:
    """幂等创建默认规则（按 rule_key 去重）。重复调用不重复建行，不覆盖既有值。"""
    existing = set((await session.execute(select(PermissionRule.rule_key))).scalars().all())
    created = False
    for spec in DEFAULT_RULES:
        if spec["rule_key"] in existing:
            continue
        session.add(
            PermissionRule(
                rule_key=spec["rule_key"],
                rule_group=spec["rule_group"],
                rule_type=spec["rule_type"],
                display_name=spec["display_name"],
                value_bool=spec.get("value_bool"),
                value_number=spec.get("value_number"),
                value_text=spec.get("value_text"),
                # 默认值与出厂值一致。
                default_bool=spec.get("value_bool"),
                default_number=spec.get("value_number"),
                default_text=spec.get("value_text"),
                unit=spec.get("unit"),
                description=spec.get("description"),
                editable=spec["editable"],
                enabled=True,
            )
        )
        created = True
    if created:
        await session.commit()


def _to_out(rule: PermissionRule, names: dict[uuid.UUID, str]) -> PermissionRuleOut:
    return PermissionRuleOut(
        rule_id=rule.id,
        rule_key=rule.rule_key,
        rule_group=rule.rule_group,
        rule_type=rule.rule_type,
        display_name=rule.display_name,
        value_bool=rule.value_bool,
        value_number=float(rule.value_number) if rule.value_number is not None else None,
        value_text=rule.value_text,
        default_bool=rule.default_bool,
        default_number=float(rule.default_number) if rule.default_number is not None else None,
        default_text=rule.default_text,
        unit=rule.unit,
        description=rule.description,
        editable=rule.editable,
        enabled=rule.enabled,
        updated_by_user_id=rule.updated_by,
        updated_by_name=names.get(rule.updated_by) if rule.updated_by else None,
        updated_at=rule.updated_at,
    )


async def _resolve_names(
    session: AsyncSession, rules: list[PermissionRule]
) -> dict[uuid.UUID, str]:
    ids = {r.updated_by for r in rules if r.updated_by}
    if not ids:
        return {}
    rows = (await session.execute(select(User.id, User.name).where(User.id.in_(ids)))).all()
    return {r[0]: r[1] for r in rows}


async def list_rules(session: AsyncSession, caller: CallerContext) -> PermissionRulesResponse:
    _require_read(caller)
    await ensure_default_rules(session)
    rules = list((await session.execute(select(PermissionRule))).scalars().all())
    # 按分组顺序、再按 key 稳定排序，便于前端分组展示。
    rules.sort(key=lambda r: (_GROUP_RANK.get(r.rule_group, 99), r.rule_key))
    names = await _resolve_names(session, rules)
    return PermissionRulesResponse(items=[_to_out(r, names) for r in rules], total=len(rules))


async def update_rule(
    session: AsyncSession,
    caller: CallerContext,
    rule_id: uuid.UUID,
    req: PermissionRuleUpdateRequest,
    trace_id: str,
) -> PermissionRuleOut:
    """更新规则取值 / 启停。仅 boss / 咨询总监；写 config.permission_rule_updated 审计。"""
    _require_write(caller)

    rule = (
        await session.execute(select(PermissionRule).where(PermissionRule.id == rule_id))
    ).scalar_one_or_none()
    if rule is None:
        raise _denied(404, "permission_rule_not_found", "权限规则不存在")

    if rule.rule_type == RULE_FIXED_PATH or not rule.editable:
        raise _denied(422, "rule_not_editable", "该规则为固定路径 / 只读，不可修改")

    before: dict = {"enabled": rule.enabled}
    after: dict = {}
    changed = False

    if rule.rule_type == RULE_NUMERIC:
        # numeric 规则只接受 value_number，且不接受 bool/text。
        if req.value_bool is not None or req.value_text is not None:
            raise _denied(422, "invalid_rule_value", "数字阈值规则只能修改数字值")
        if req.value_number is not None:
            if req.value_number < 0:
                raise _denied(422, "invalid_rule_value", "数字阈值不能为负")
            before["value_number"] = (
                float(rule.value_number) if rule.value_number is not None else None
            )
            rule.value_number = float(req.value_number)
            after["value_number"] = float(rule.value_number)
            changed = True
    elif rule.rule_type == RULE_TOGGLE:
        # toggle 规则只接受 value_bool。
        if req.value_number is not None or req.value_text is not None:
            raise _denied(422, "invalid_rule_value", "开关规则只能修改布尔值")
        if req.value_bool is not None:
            before["value_bool"] = rule.value_bool
            rule.value_bool = bool(req.value_bool)
            after["value_bool"] = rule.value_bool
            changed = True

    if req.enabled is not None and req.enabled != rule.enabled:
        rule.enabled = bool(req.enabled)
        after["enabled"] = rule.enabled
        changed = True

    if not changed:
        raise _denied(422, "no_rule_change", "未提供任何可更新的取值")

    rule.updated_by = caller.user_id
    await session.flush()

    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.config_permission_rule_updated.value,
        trace_id=trace_id,
        target_type="permission_rule",
        target_id=rule.id,
        before=before,
        after=after,
        # 只记安全配置元数据；绝不记 secret / provider 内部标识 / 业务原文。
        extra={
            "rule_key": rule.rule_key,
            "rule_group": rule.rule_group,
            "rule_type": rule.rule_type,
        },
    )
    await session.commit()
    names = await _resolve_names(session, [rule])
    return _to_out(rule, names)

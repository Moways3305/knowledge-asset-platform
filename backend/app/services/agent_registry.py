"""外部 Agent 接入注册服务。

负责 `agent_whitelist_rules` 的 token 哈希 / 鉴权查询 / 管理 CRUD。注册行 provider 中立
（`provider` 列区分 workbuddy / custom 等），管理与鉴权逻辑不绑定任何具体 provider。

安全红线：
- **绝不存 / 返回明文 token**：只存 `token_hash`（sha256）。明文仅在创建/重置时**一次性**
  返回给管理员，之后不可再取。
- 响应**绝不**含 token_hash / provider 内部标识（app/workflow id）/ agent_identifier。
- 管理端为 admin 系统身份（外部 Agent 接入是系统配置，非业务知识访问，不触碰 admin 业务边界）。
"""

from __future__ import annotations

import hashlib
import secrets
import uuid

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.utils import utc_now
from app.models.agent_registry import AgentWhitelistRule
from app.models.identity import User
from app.schemas.enums import AuditAction, AuditLogType, CompanyRole
from app.schemas.external_agent import RegistryRuleOut
from app.schemas.permission import CallerContext
from app.services import audit as audit_service
from app.services.identity import load_user_with_roles
from app.services.permission import build_caller_context


def hash_token(token: str) -> str:
    """Bearer token → sha256 hex（绝不存明文）。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_token() -> str:
    """生成新的外部 Agent 接入 token（明文仅一次性返回，不入库）。"""
    return "kgw_" + secrets.token_urlsafe(32)


async def record_successful_connection(
    session: AsyncSession,
    rule_id: uuid.UUID,
) -> None:
    """Persist a successful WorkBuddy request without exposing ORM writes to the API layer."""
    await session.execute(
        update(AgentWhitelistRule)
        .where(
            AgentWhitelistRule.id == rule_id,
            AgentWhitelistRule.provider == "workbuddy",
        )
        .values(last_connected_at=utc_now())
    )
    await session.commit()


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"denied_reason": reason, "message": message}
    )


def _require_admin(caller: CallerContext) -> None:
    """外部 Agent 注册管理仅 admin（系统集成配置）。非 admin → 403。"""
    if CompanyRole.admin.value not in caller.active_company_roles:
        raise _denied(403, "agent_registry_admin_only", "仅 admin 可管理外部 Agent 接入注册")


def _to_out(rule: AgentWhitelistRule, bound_user: User | None = None) -> RegistryRuleOut:
    """安全视图：不含 token_hash / provider 内部标识 / agent_identifier。"""
    name = None
    active = None
    if bound_user is not None:
        name = bound_user.name
        active = bound_user.status == "active" and build_caller_context(bound_user).is_business_user
    return RegistryRuleOut(
        id=rule.id,
        provider=rule.provider,
        agent_name=rule.agent_name,
        capability=rule.capability,
        allowed_scope=rule.allowed_scope,
        allowed_project_id=rule.allowed_project_id,
        max_confidentiality_level=rule.max_confidentiality_level,
        max_ai_access_level=rule.max_ai_access_level,
        enabled=rule.enabled,
        bound_user_id=rule.bound_user_id,
        bound_user_name=name,
        bound_user_active=active,
        risk_level=rule.risk_level,
        risk_note=rule.risk_note,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


async def _validate_binding(session: AsyncSession, req) -> User | None:
    """校验 bound_user_id：workbuddy 必填；任何绑定必须指向 active 业务用户（禁 admin/inactive）。"""
    bound_id = getattr(req, "bound_user_id", None)
    if bound_id is None:
        if req.provider == "workbuddy":
            raise _denied(400, "bound_user_required", "workbuddy 接入必须绑定一个业务用户")
        return None
    user = await load_user_with_roles(session, user_id=bound_id)
    if user is None or user.status != "active" or not build_caller_context(user).is_business_user:
        raise _denied(400, "bound_user_invalid", "绑定用户不存在 / 已停用 / 非业务用户")
    return user


async def lookup_enabled_rule(session: AsyncSession, token: str) -> AgentWhitelistRule | None:
    """按明文 token 的哈希查启用中的注册行。无匹配 / 未启用 → None。"""
    if not token:
        return None
    th = hash_token(token)
    rule = (
        await session.execute(
            select(AgentWhitelistRule).where(
                AgentWhitelistRule.token_hash == th,
                AgentWhitelistRule.enabled.is_(True),
            )
        )
    ).scalar_one_or_none()
    return rule


# ---------------------------------------------------------------------------
# 管理 CRUD（admin-only）
# ---------------------------------------------------------------------------
async def list_rules(session: AsyncSession, caller: CallerContext):
    from app.schemas.external_agent import RegistryListResponse

    _require_admin(caller)
    rows = list(
        (await session.execute(select(AgentWhitelistRule).order_by(AgentWhitelistRule.created_at)))
        .scalars()
        .all()
    )
    # bound_user_active 需读 company_roles → 用 load_user_with_roles 预加载（避免 async 懒加载）。
    users_by_id: dict = {}
    for bid in {r.bound_user_id for r in rows if r.bound_user_id is not None}:
        u = await load_user_with_roles(session, user_id=bid)
        if u is not None:
            users_by_id[bid] = u
    return RegistryListResponse(items=[_to_out(r, users_by_id.get(r.bound_user_id)) for r in rows])


async def create_rule(session: AsyncSession, caller: CallerContext, req, trace_id: str | None):
    """创建接入注册行，生成 token（明文一次性返回）。"""
    from app.schemas.external_agent import RegistryCreateResponse

    _require_admin(caller)
    bound_user = await _validate_binding(session, req)

    # workbuddy 自助接入每用户仅允许一枚注册行（agent_identifier 约定为
    # "workbuddy:self:{bound_user_id}"）。管理端创建路径需在落库前显式校验，
    # 避免重复创建导致 (provider, bound_user_id) 冲突（即便有 DB 唯一索引，
    # 此处也提前返回语义清晰的 409，而非让 IntegrityError 冒泡成 500）。
    if req.provider == "workbuddy" and bound_user is not None:
        existing = (
            (
                await session.execute(
                    select(AgentWhitelistRule).where(
                        AgentWhitelistRule.provider == "workbuddy",
                        AgentWhitelistRule.bound_user_id == bound_user.id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            raise _denied(
                409,
                "workbuddy_rule_already_exists",
                "该业务用户已存在 WorkBuddy 接入注册，请使用更新 / 重置而非重复创建",
            )

    token = generate_token()
    rule = AgentWhitelistRule(
        provider=req.provider,
        agent_identifier=req.agent_identifier,
        agent_name=req.agent_name,
        capability=req.capability,
        allowed_scope=req.allowed_scope,
        allowed_project_id=req.allowed_project_id,
        max_confidentiality_level=req.max_confidentiality_level,
        max_ai_access_level=req.max_ai_access_level,
        token_hash=hash_token(token),
        enabled=req.enabled,
        is_self_service=False,  # 管理员 CRUD 永远不能签发自助来源标记
        risk_level=req.risk_level,
        risk_note=req.risk_note,
        external_app_id=req.external_app_id,
        external_workflow_id=req.external_workflow_id,
        bound_user_id=bound_user.id if bound_user is not None else None,
    )
    session.add(rule)
    await session.flush()
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.config_agent_registry_updated.value,
        trace_id=trace_id,
        target_type="agent_whitelist_rule",
        target_id=rule.id,
        # 只记安全元数据；绝不记 token / token_hash / external_*。
        extra={
            "op": "create",
            "provider": rule.provider,
            "capability": rule.capability,
            "enabled": rule.enabled,
        },
    )
    await session.commit()
    return RegistryCreateResponse(rule=_to_out(rule, bound_user), token=token)


async def update_rule(
    session: AsyncSession, caller: CallerContext, rule_id: uuid.UUID, req, trace_id: str | None
):
    """更新启停 / capability / scope / 风险；可选重置 token（明文一次性返回）。"""
    from app.schemas.external_agent import RegistryCreateResponse

    _require_admin(caller)
    rule = (
        await session.execute(select(AgentWhitelistRule).where(AgentWhitelistRule.id == rule_id))
    ).scalar_one_or_none()
    if rule is None:
        raise _denied(404, "agent_registry_not_found", "接入注册不存在")

    changed: dict = {}
    if req.enabled is not None:
        rule.enabled = req.enabled
        changed["enabled"] = req.enabled
    if req.capability is not None:
        rule.capability = req.capability
        changed["capability"] = req.capability
    if req.allowed_scope is not None:
        rule.allowed_scope = req.allowed_scope
        changed["allowed_scope"] = req.allowed_scope
    if req.allowed_project_id is not None:
        rule.allowed_project_id = req.allowed_project_id
    if req.max_confidentiality_level is not None:
        rule.max_confidentiality_level = req.max_confidentiality_level
        changed["max_confidentiality_level"] = req.max_confidentiality_level
    if req.max_ai_access_level is not None:
        rule.max_ai_access_level = req.max_ai_access_level
    if req.risk_level is not None:
        rule.risk_level = req.risk_level
    if req.risk_note is not None:
        rule.risk_note = req.risk_note

    new_token: str | None = None
    if req.regenerate_token:
        new_token = generate_token()
        rule.token_hash = hash_token(new_token)
        changed["token"] = "regenerated"

    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.config_agent_registry_updated.value,
        trace_id=trace_id,
        target_type="agent_whitelist_rule",
        target_id=rule.id,
        extra={"op": "update", **changed},  # 不含 token 明文 / token_hash
    )
    bound_user = (
        await load_user_with_roles(session, user_id=rule.bound_user_id)
        if rule.bound_user_id is not None
        else None
    )
    await session.commit()
    return RegistryCreateResponse(rule=_to_out(rule, bound_user), token=new_token)

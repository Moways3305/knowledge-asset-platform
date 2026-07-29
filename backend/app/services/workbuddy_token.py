"""自助 WorkBuddy 接入 token 服务。

当前登录的**业务用户**自助生成 / 重置 / 撤销一枚 WorkBuddy Agent token。token 在
`agent_whitelist_rules` 中**绑定当前用户**（`bound_user_id = caller.user_id`），与管理员
后台的 provider/能力/保密级配置无关，也不允许调用方指定绑定对象或更高权限。

安全红线：
- 绑定对象由服务端强制为 caller 本人，**忽略任何请求体传入的 bound_user_id**。
- 明文 token 仅在生成 / 重置那一刻返回一次；库里只存 sha256。
- 仅 active 业务用户可用（pure admin / inactive / 非业务用户 → 403）。
- 审计只记安全元数据（provider / bound_user_id / operation），绝不记 token / token_hash。
"""

from __future__ import annotations

from urllib.parse import urlsplit

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import denied
from app.db.utils import utc_now
from app.models.agent_registry import AgentWhitelistRule
from app.schemas.enums import AuditAction, AuditLogType
from app.schemas.permission import CallerContext
from app.schemas.workbuddy import (
    WorkbuddyPlatform,
    WorkbuddyTokenCreatedOut,
    WorkbuddyTokenStatusOut,
)
from app.services import agent_registry
from app.services import audit as audit_service
from app.services.identity import load_user_with_roles

_PROVIDER = "workbuddy"
_CAPABILITY = "qa"
# 自助 token 完全跟随绑定用户的实时 KAP 权限。字段仍写模型合法最大值以兼容旧表结构，
# agent gateway 会按精确 self-service identifier 跳过 registry ceiling。
_MAX_CONF = "L5"
_MAX_AI = "A4"


def _require_business(caller: CallerContext) -> None:
    """仅 active 业务用户可自助接入（禁 pure admin / inactive / 非业务用户）。"""
    if not caller.is_active or not caller.is_business_user:
        raise denied(
            403, "workbuddy_not_business_user", "仅在职业务用户可自助生成 WorkBuddy 接入配置"
        )


def _identifier(user_id) -> str:
    """每用户一枚自助 token：用稳定 identifier 保证 upsert 唯一。"""
    return f"workbuddy:self:{user_id}"


async def _find_rule(session: AsyncSession, user_id) -> AgentWhitelistRule | None:
    # 容错：历史上可能存在 (provider, bound_user_id) 重复行，scalar_one_or_none()
    # 在多行时会抛 MultipleResultsFound → 自助端点全 500。改用 first() + 排序：
    # enabled 优先、最新优先，确保即便有重复行也能稳定返回一行，先止血。
    return (
        (
            await session.execute(
                select(AgentWhitelistRule)
                .where(
                    AgentWhitelistRule.provider == _PROVIDER,
                    AgentWhitelistRule.bound_user_id == user_id,
                    AgentWhitelistRule.is_self_service.is_(True),
                )
                .order_by(desc(AgentWhitelistRule.enabled), desc(AgentWhitelistRule.created_at))
            )
        )
        .scalars()
        .first()
    )


def _connector_command(platform: WorkbuddyPlatform) -> str:
    if platform == "windows":
        return r"C:\Program Files\KAP WorkBuddy Connector\kap-workbuddy-connector.exe"
    return "/Applications/KAP WorkBuddy Connector.app/Contents/MacOS/kap-workbuddy-connector"


def _mcp_config(base_url: str, token: str, platform: WorkbuddyPlatform) -> dict:
    """可直接复制到 WorkBuddy `mcp.json` 的本地 stdio 配置。"""
    return {
        "mcpServers": {
            "kap": {
                "command": _connector_command(platform),
                "env": {"KAP_BASE_URL": base_url, "KAP_AGENT_TOKEN": token},
            }
        }
    }


def public_base_url() -> str:
    """返回服务器控制的规范 origin；生产缺失或非 HTTPS 时 fail closed。"""
    settings = get_settings()
    raw = (settings.kap_public_base_url or "").strip()
    parsed = urlsplit(raw)
    valid = (
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
        and not any(char.isspace() for char in raw)
    )
    if not valid or (settings.app_env == "prod" and parsed.scheme != "https"):
        raise denied(
            503,
            "workbuddy_public_base_url_invalid",
            "WorkBuddy 公网连接地址尚未安全配置",
        )
    try:
        parsed_port = parsed.port
    except ValueError:
        raise denied(
            503,
            "workbuddy_public_base_url_invalid",
            "WorkBuddy 公网连接地址尚未安全配置",
        ) from None
    hostname = parsed.hostname or ""
    if ":" in hostname:
        hostname = f"[{hostname}]"
    port = f":{parsed_port}" if parsed_port is not None else ""
    return f"{parsed.scheme}://{hostname}{port}"


async def get_status(session: AsyncSession, caller: CallerContext) -> WorkbuddyTokenStatusOut:
    _require_business(caller)
    user = await load_user_with_roles(session, user_id=caller.user_id)
    name = user.name if user is not None else None
    rule = await _find_rule(session, caller.user_id)
    if rule is None or not rule.enabled:
        return WorkbuddyTokenStatusOut(enabled=False, bound_user_name=name)
    return WorkbuddyTokenStatusOut(
        enabled=True,
        provider=rule.provider,
        bound_user_name=name,
        last_rotated_at=rule.token_rotated_at,
        last_connected_at=rule.last_connected_at,
    )


async def regenerate(
    session: AsyncSession,
    caller: CallerContext,
    *,
    platform: WorkbuddyPlatform,
    trace_id: str | None,
) -> WorkbuddyTokenCreatedOut:
    """为当前业务用户创建或重置自助 token（绑定 caller 本人；明文一次性返回）。"""
    _require_business(caller)
    base_url = public_base_url()
    token = agent_registry.generate_token()
    token_hash = agent_registry.hash_token(token)
    now = utc_now()
    rule = await _find_rule(session, caller.user_id)
    if rule is None:
        managed_rule = (
            (
                await session.execute(
                    select(AgentWhitelistRule).where(
                        AgentWhitelistRule.provider == _PROVIDER,
                        AgentWhitelistRule.bound_user_id == caller.user_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if managed_rule is not None:
            raise denied(
                409,
                "workbuddy_managed_rule_exists",
                "该用户已有管理员维护的 WorkBuddy 接入，请联系管理员处理",
            )
        rule = AgentWhitelistRule(
            provider=_PROVIDER,
            agent_identifier=_identifier(caller.user_id),
            agent_name="WorkBuddy 自助接入",
            capability=_CAPABILITY,
            max_confidentiality_level=_MAX_CONF,
            max_ai_access_level=_MAX_AI,
            token_hash=token_hash,
            enabled=True,
            is_self_service=True,
            bound_user_id=caller.user_id,  # 服务端强制绑定 caller，忽略任何外部输入
            token_rotated_at=now,
        )
        session.add(rule)
    else:
        rule.token_hash = token_hash  # 旧 token 立即失效
        rule.enabled = True
        rule.capability = _CAPABILITY
        rule.max_confidentiality_level = _MAX_CONF
        rule.max_ai_access_level = _MAX_AI
        rule.token_rotated_at = now
    # 新 token 尚未完成任何真实调用，不能继承旧 token 的连接成功状态。
    rule.last_connected_at = None
    await session.flush()
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.agent_workbuddy_token_rotated.value,
        trace_id=trace_id,
        target_type="agent_whitelist_rule",
        target_id=rule.id,
        extra={"provider": _PROVIDER, "operation": "rotate"},
    )
    await session.commit()
    return WorkbuddyTokenCreatedOut(
        token=token,
        mcp_config=_mcp_config(base_url, token, platform),
        platform=platform,
    )


async def revoke(
    session: AsyncSession, caller: CallerContext, *, trace_id: str | None
) -> WorkbuddyTokenStatusOut:
    """撤销当前用户自助 token（enabled=False，旧 token 立即不可用）。幂等。"""
    _require_business(caller)
    rule = await _find_rule(session, caller.user_id)
    if rule is not None and rule.enabled:
        rule.enabled = False
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.agent_workbuddy_token_revoked.value,
            trace_id=trace_id,
            target_type="agent_whitelist_rule",
            target_id=rule.id,
            extra={
                "provider": _PROVIDER,
                "operation": "revoke",
            },
        )
    await session.commit()
    user = await load_user_with_roles(session, user_id=caller.user_id)
    return WorkbuddyTokenStatusOut(
        enabled=False, bound_user_name=user.name if user is not None else None
    )

"""Auth / 会话身份 API（IMPLEMENT-12 真实会话身份最小闭环）。

- POST /api/v1/auth/login：本地登录（开发环境无凭证适配器）→ 建会话、下发 httpOnly
  cookie、写 login.success 审计；失败写 login.failed（有已知用户时）并 401。
- POST /api/v1/auth/logout：撤销会话、清 cookie、写 login.logout 审计。
- GET  /api/v1/auth/me：返回当前身份（会话优先；开发环境回退 X-Dev-User-Id）。

安全：明文会话 token 只经 Set-Cookie（httpOnly）下发，**绝不进入任何 JSON 响应体**；
服务端只存 token 的 sha256 哈希。真实 OAuth / 密码校验为后续任务。
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.trace import get_trace_id
from app.schemas.auth import AuthMeOut, LoginRequest, LogoutResponse, WecomAuthorizeOut
from app.schemas.enums import AuditAction, AuditLogType
from app.db.session import get_db
from app.services import audit as audit_service
from app.services import auth_session as session_service
from app.services.auth_session import SESSION_COOKIE_NAME
from app.services.identity import build_auth_me, load_user_with_roles
from app.services.permission import build_caller_context
from app.services.wecom_client import WeComError, get_wecom_oauth_client

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# cookie 最大存活（秒），与会话 TTL 对齐。
_COOKIE_MAX_AGE = session_service.SESSION_TTL_HOURS * 3600
# OAuth state 短时 httpOnly cookie（防 CSRF）。
_OAUTH_STATE_COOKIE = "kap_oauth_state"
_OAUTH_STATE_MAX_AGE = 600  # 10 分钟


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    """提取审计 / 会话用的非敏感客户端元数据（IP、User-Agent 截断）。"""
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    return ip, (ua[:480] if ua else None)


@router.post("/login", response_model=AuthMeOut)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> AuthMeOut:
    """本地无凭证登录（仅开发环境）。建会话 + 下发 httpOnly cookie + 登录审计。"""
    settings = get_settings()
    trace_id = get_trace_id(request)
    ip, device = _client_meta(request)

    try:
        user = await session_service.login_local(
            session, app_env=settings.app_env, email=body.email
        )
    except session_service._InvalidCredentials as exc:
        # 有已知用户（如非 active）才写 login.failed（需真实 actor 归属）。
        if exc.user_id is not None:
            failed_user = await session_service.load_user_with_roles(
                session, user_id=exc.user_id
            )
            if failed_user is not None:
                await audit_service.record_denied(
                    session,
                    caller=build_caller_context(failed_user),
                    log_type=AuditLogType.login,
                    action=AuditAction.login_failed.value,
                    trace_id=trace_id,
                    extra={
                        "login_result": "failed",
                        "login_method": "dev_local",
                        "ip_address": ip,
                    },
                )
        raise HTTPException(
            status_code=401,
            detail={"denied_reason": "invalid_credentials", "message": "登录失败"},
        )

    raw_token = await session_service.create_session(
        session, user, ip_address=ip, device_info=device, login_method="dev_local"
    )
    await audit_service.record_event(
        session,
        caller=build_caller_context(user),
        log_type=AuditLogType.login,
        action=AuditAction.login_success.value,
        trace_id=trace_id,
        extra={
            "login_result": "success",
            "login_method": "dev_local",
            "ip_address": ip,
        },
    )
    await session.commit()

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        max_age=_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=False,  # 本地 http；生产应置 True（HTTPS）。
        path="/",
    )
    return build_auth_me(user)


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    request: Request,
    response: Response,
    kap_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    session: AsyncSession = Depends(get_db),
) -> LogoutResponse:
    """撤销当前会话并清 cookie。"""
    trace_id = get_trace_id(request)
    # 撤销前先取归属用户（撤销后会话不可解析），用于登出审计。
    actor = await session_service.resolve_session_user(session, kap_session)
    revoked = await session_service.revoke_session(session, kap_session)
    if revoked and actor is not None:
        await audit_service.record_event(
            session,
            caller=build_caller_context(actor),
            log_type=AuditLogType.login,
            action=AuditAction.login_logout.value,
            trace_id=trace_id,
            extra={"login_method": "dev_local"},
        )
    if revoked:
        await session.commit()
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return LogoutResponse(ok=revoked)


@router.get("/wecom/start", response_model=WecomAuthorizeOut)
async def wecom_start(
    response: Response,
    oauth=Depends(get_wecom_oauth_client),
) -> WecomAuthorizeOut:
    """生成 state 绑定的企微授权 URL；state 写入短时 httpOnly cookie（不进 JSON 响应体）。"""
    state = secrets.token_urlsafe(24)
    try:
        url = oauth.build_authorize_url(state=state)
    except WeComError as exc:
        raise HTTPException(status_code=503, detail={"denied_reason": exc.code, "message": "企微未配置"})
    response.set_cookie(
        key=_OAUTH_STATE_COOKIE, value=state, max_age=_OAUTH_STATE_MAX_AGE,
        httponly=True, samesite="lax", secure=False, path="/",
    )
    # 授权 URL 含 corp_id/redirect/state，但**不含 app_secret**；state 同时在 cookie 里校验。
    return WecomAuthorizeOut(authorize_url=url)


@router.get("/wecom/callback", response_model=AuthMeOut)
async def wecom_callback(
    request: Request,
    response: Response,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    kap_oauth_state: str | None = Cookie(default=None, alias=_OAUTH_STATE_COOKIE),
    oauth=Depends(get_wecom_oauth_client),
    session: AsyncSession = Depends(get_db),
) -> AuthMeOut:
    """企微 OAuth 回调：校验 state → 换身份 → 解析平台用户 → 建会话。fail closed。

    安全：code / access_token / state 绝不持久化或进 JSON 响应；state 用后即清。
    """
    trace_id = get_trace_id(request)
    ip, device = _client_meta(request)
    # state 校验（CSRF）：query state 必须存在且与 cookie 一致。
    response.delete_cookie(key=_OAUTH_STATE_COOKIE, path="/")
    if not state or not kap_oauth_state or not secrets.compare_digest(state, kap_oauth_state):
        raise HTTPException(status_code=400, detail={"denied_reason": "oauth_state_invalid", "message": "state 校验失败"})
    if not code:
        raise HTTPException(status_code=400, detail={"denied_reason": "oauth_code_missing", "message": "缺少 code"})

    try:
        identity = await oauth.exchange_code(code)
    except WeComError as exc:
        # 上游换取失败：只暴露安全 code，不回显原始 payload。
        raise HTTPException(status_code=401, detail={"denied_reason": "oauth_exchange_failed", "message": "企微身份换取失败"})

    user = await load_user_with_roles(session, wecom_user_id=identity.wecom_user_id)
    if user is None:
        # 未绑定平台用户：fail closed，不自动建用户（R6 不做 auto-provision）。
        raise HTTPException(status_code=403, detail={"denied_reason": "user_not_provisioned", "message": "企微用户未绑定平台账号"})
    if user.status != "active":
        # 已知用户但非 active → 写 login.failed（可安全归属）后 401。
        await audit_service.record_denied(
            session, caller=build_caller_context(user), log_type=AuditLogType.login,
            action=AuditAction.login_failed.value, trace_id=trace_id,
            extra={"login_result": "failed", "login_method": "wecom_oauth", "ip_address": ip},
        )
        raise HTTPException(status_code=401, detail={"denied_reason": "user_inactive", "message": "用户已停用"})

    raw_token = await session_service.create_session(
        session, user, ip_address=ip, device_info=device, login_method="wecom_oauth"
    )
    await audit_service.record_event(
        session, caller=build_caller_context(user), log_type=AuditLogType.login,
        action=AuditAction.login_success.value, trace_id=trace_id,
        # 只记安全元数据：登录方式 + 安全 provider 标记 + ip；**绝不**记 code/token/state。
        extra={"login_result": "success", "login_method": "wecom_oauth", "provider": "wecom", "ip_address": ip},
    )
    await session.commit()
    response.set_cookie(
        key=SESSION_COOKIE_NAME, value=raw_token, max_age=_COOKIE_MAX_AGE,
        httponly=True, samesite="lax", secure=False, path="/",
    )
    return build_auth_me(user)


@router.get("/me", response_model=AuthMeOut)
async def auth_me(
    x_dev_user_id: str | None = Header(default=None, alias="X-Dev-User-Id"),
    kap_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    session: AsyncSession = Depends(get_db),
) -> AuthMeOut:
    """返回当前用户身份上下文（会话优先；开发环境回退 X-Dev-User-Id / 默认开发用户）。"""
    settings = get_settings()
    user = await session_service.resolve_current_user(
        session,
        app_env=settings.app_env,
        session_token=kap_session,
        dev_user_id=x_dev_user_id,
    )
    return build_auth_me(user)

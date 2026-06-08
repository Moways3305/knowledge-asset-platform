"""Auth / 会话身份 API。

- POST /api/v1/auth/login：本地登录（开发环境无凭证适配器）→ 建会话、下发 httpOnly
  cookie、写 login.success 审计；失败写 login.failed（有已知用户时）并 401。
- POST /api/v1/auth/logout：撤销会话、清 cookie、写 login.logout 审计。
- GET  /api/v1/auth/me：返回当前身份（会话优先；开发环境回退 X-Dev-User-Id）。

安全：明文会话 token 只经 Set-Cookie（httpOnly）下发，**绝不进入任何 JSON 响应体**；
服务端只存 token 的 sha256 哈希。密码登录与企业微信 OAuth 经各自端点校验后建会话。
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings, session_cookie_secure
from app.core.trace import get_trace_id
from app.schemas.auth import (
    AuthMeOut,
    CsrfTokenOut,
    LoginRequest,
    LogoutResponse,
    WecomAuthorizeOut,
)
from app.schemas.enums import AuditAction, AuditLogType
from app.db.session import get_db
from app.services import audit as audit_service
from app.services import auth_security as auth_security
from app.services import auth_session as session_service
from app.services import csrf as csrf_service
from app.services import wecom_identity
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


def _set_session_cookie(response: Response, raw_token: str, settings) -> None:
    """统一下发会话 cookie：httpOnly + samesite=lax + 环境派生 Secure。

    Secure 由 `session_cookie_secure(settings)` 统一决定（prod 强制 True），避免三处入口
    各自硬编码 secure=False 再次分叉。明文 token 只经 Set-Cookie，绝不进 JSON。"""
    response.set_cookie(
        key=SESSION_COOKIE_NAME, value=raw_token, max_age=_COOKIE_MAX_AGE,
        httponly=True, samesite="lax", secure=session_cookie_secure(settings), path="/",
    )


def _set_oauth_state_cookie(response: Response, state: str, settings) -> None:
    """统一下发 OAuth state 短时 cookie，Secure 口径与会话 cookie 一致。"""
    response.set_cookie(
        key=_OAUTH_STATE_COOKIE, value=state, max_age=_OAUTH_STATE_MAX_AGE,
        httponly=True, samesite="lax", secure=session_cookie_secure(settings), path="/",
    )


async def _record_login_failed(
    session, *, user_id, login_method, trace_id, ip, reason_code, identifier_hash
) -> None:
    """已知用户写 login.failed（需真实 actor 归属）；未知 email（user_id=None）不写归属审计，
    改由系统事件 `_record_system_login_event` 记录不可逆安全线索（避免伪造 actor / 账号枚举）。"""
    if user_id is None:
        return
    failed_user = await session_service.load_user_with_roles(session, user_id=user_id)
    if failed_user is not None:
        await audit_service.record_denied(
            session, caller=build_caller_context(failed_user), log_type=AuditLogType.login,
            action=AuditAction.login_failed.value, trace_id=trace_id,
            # 已知用户沿用既有归属审计口径（含 ip_address）；补安全 reason_code + hash 前缀。
            extra={
                "login_result": "failed", "login_method": login_method, "ip_address": ip,
                "reason_code": reason_code,
                "identifier_hash_prefix": auth_security.hash_prefix(identifier_hash),
            },
        )
        await session.commit()


async def _record_system_login_event(
    session, *, action, login_method, trace_id, reason_code,
    identifier_hash, ip_hash, failed_count, window_minutes=None, lockout_minutes=None,
) -> None:
    """未知 email / 锁定 / 限流的系统级安全审计（actor=None）。

    extra 只含不可逆 hash 前缀 / reason_code / 计数 / 窗口——**绝不**含 raw email / 原始 IP /
    password / token / cookie。提交由调用方负责（与 attempt 写入同一事务）。"""
    extra = {
        "login_result": "failed",
        "login_method": login_method,
        "reason_code": reason_code,
        "identifier_hash_prefix": auth_security.hash_prefix(identifier_hash),
        "ip_hash_prefix": auth_security.hash_prefix(ip_hash),
        "failed_count": failed_count,
    }
    if window_minutes is not None:
        extra["window_minutes"] = window_minutes
    if lockout_minutes is not None:
        extra["lockout_minutes"] = lockout_minutes
    await audit_service.record_system_event(
        session, log_type=AuditLogType.login, action=action, trace_id=trace_id, extra=extra,
    )


@router.post("/login", response_model=AuthMeOut)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> AuthMeOut:
    """密码凭证登录。提供 password → 所有环境校验密码（login_method=password）；
    不提供 password → 仅 local/dev/test 走无凭证开发适配器（dev_local），prod 拒绝。
    建会话 + 下发 httpOnly cookie + 登录审计。明文 token 只经 Set-Cookie，不进 JSON。"""
    settings = get_settings()
    trace_id = get_trace_id(request)
    ip, device = _client_meta(request)

    has_password = bool(body.password)
    login_method = "password" if has_password else "dev_local"

    # 不可逆登录标识 / IP hash。raw email / IP 绝不进响应 / 审计。
    identifier = auth_security.normalize_login_identifier(body.email)
    identifier_hash = auth_security.hash_login_identifier(identifier, purpose="identifier")
    ip_hash = auth_security.hash_login_identifier(ip, purpose="ip") if ip else None

    _unified_401 = HTTPException(
        status_code=401,
        # 统一文案，不区分用户是否存在 / 密码错误 / 未设密码 / inactive / 锁定 / 限流。
        detail={"denied_reason": "invalid_credentials", "message": "邮箱或密码错误，请稍后再试"},
    )

    if not has_password and settings.app_env not in session_service.LOGIN_ALLOWED_ENVS:
        # 生产环境必须提供密码（无凭证开发入口仅 local/dev/test）。
        raise HTTPException(
            status_code=403,
            detail={"denied_reason": "auth_password_required", "message": "请输入密码登录"},
        )

    # 守卫：仅 password 登录参与失败锁定 / IP 限流。命中则**不做真实 PBKDF2 校验**
    # （资源保护——不在暴力尝试下持续消耗 PBKDF2），直接安全拒绝并记录系统审计。
    if has_password:
        guard = await auth_security.check_login_guard(
            session, identifier_hash=identifier_hash, ip_hash=ip_hash, settings=settings
        )
        if guard.blocked:
            await auth_security.record_login_attempt(
                session, identifier_hash=identifier_hash, ip_hash=ip_hash, user_id=None,
                login_method=login_method, result=guard.result, reason_code=guard.reason_code,
                trace_id=trace_id,
            )
            action = (
                AuditAction.login_locked.value
                if guard.result == "locked"
                else AuditAction.login_rate_limited.value
            )
            await _record_system_login_event(
                session, action=action, login_method=login_method, trace_id=trace_id,
                reason_code=guard.reason_code, identifier_hash=identifier_hash, ip_hash=ip_hash,
                failed_count=guard.failed_count, window_minutes=guard.window_minutes,
                lockout_minutes=guard.lockout_minutes,
            )
            await session.commit()
            raise _unified_401

    try:
        if has_password:
            user = await session_service.login_with_password(
                session, email=body.email, password=body.password
            )
        else:
            user = await session_service.login_local(
                session, app_env=settings.app_env, email=body.email
            )
    except session_service._InvalidCredentials as exc:
        # 记录失败尝试（不可逆统计驱动锁定）；已知用户走归属审计，未知 email 走系统审计。
        await auth_security.record_login_attempt(
            session, identifier_hash=identifier_hash, ip_hash=ip_hash, user_id=exc.user_id,
            login_method=login_method, result="failed", reason_code="invalid_credentials",
            trace_id=trace_id,
        )
        if exc.user_id is not None:
            await _record_login_failed(
                session, user_id=exc.user_id, login_method=login_method, trace_id=trace_id,
                ip=ip, reason_code="invalid_credentials", identifier_hash=identifier_hash,
            )
        else:
            # 未知 email：不写可归属 actor，改记不可逆系统安全线索（无 raw email / IP）。
            await _record_system_login_event(
                session, action=AuditAction.login_failed.value, login_method=login_method,
                trace_id=trace_id, reason_code="invalid_credentials",
                identifier_hash=identifier_hash, ip_hash=ip_hash, failed_count=0,
            )
            await session.commit()
        raise _unified_401

    raw_token = await session_service.create_session(
        session, user, ip_address=ip, device_info=device, login_method=login_method
    )
    # 成功登录 → success attempt（后续 identifier 失败计数从此重置）。
    await auth_security.record_login_success(
        session, identifier_hash=identifier_hash, ip_hash=ip_hash, user_id=user.id,
        login_method=login_method, trace_id=trace_id,
    )
    await audit_service.record_event(
        session, caller=build_caller_context(user), log_type=AuditLogType.login,
        action=AuditAction.login_success.value, trace_id=trace_id,
        extra={"login_result": "success", "login_method": login_method, "ip_address": ip},
    )
    await session.commit()

    _set_session_cookie(response, raw_token, settings)
    return build_auth_me(user)


@router.get("/csrf", response_model=CsrfTokenOut)
async def issue_csrf(
    kap_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> CsrfTokenOut:
    """签发 CSRF token。GET（安全方法，自身不需 CSRF）。

    token 绑定当前会话（有 kap_session cookie 时）或匿名（无会话）；前端登录后应重新获取以
    绑定新会话。**不返回** session token / cookie 值 / secret。"""
    token, expires_at = csrf_service.issue_csrf_token(kap_session)
    return CsrfTokenOut(csrf_token=token, expires_at=expires_at)


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    request: Request,
    response: Response,
    kap_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    session: AsyncSession = Depends(get_db),
) -> LogoutResponse:
    """撤销当前会话并清 cookie。"""
    trace_id = get_trace_id(request)
    # 撤销前先取归属用户与真实会话来源（撤销后会话不可解析），用于登出审计。
    actor = await session_service.resolve_session_user(session, kap_session)
    login_method = await session_service.session_login_method(session, kap_session)
    revoked = await session_service.revoke_session(session, kap_session)
    if revoked and actor is not None:
        await audit_service.record_event(
            session,
            caller=build_caller_context(actor),
            log_type=AuditLogType.login,
            action=AuditAction.login_logout.value,
            trace_id=trace_id,
            # login_method 取被撤销会话的真实来源（password / dev_local / wecom_oauth），
            # 不再硬编码 dev_local。找不到来源（理论不可达，actor 已存在）退化为 unknown。
            extra={"login_method": login_method or "unknown"},
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
    _set_oauth_state_cookie(response, state, get_settings())
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

    # 建会话前先核验企微成员有效性。fail-closed。
    try:
        member = await oauth.get_member_status(identity.wecom_user_id)
    except WeComError:
        # 上游 / 未配置失败：不建会话、**不**改平台状态（避免瞬时上游故障误停用），写安全 login.failed。
        await audit_service.record_denied(
            session, caller=build_caller_context(user), log_type=AuditLogType.login,
            action=AuditAction.login_failed.value, trace_id=trace_id,
            extra={"login_result": "failed", "login_method": "wecom_oauth",
                   "reason_code": "wecom_status_check_failed", "wecom_status": "unknown", "ip_address": ip},
        )
        raise HTTPException(status_code=401, detail={"denied_reason": "wecom_status_check_failed", "message": "企微成员状态核验失败，请稍后重试"})
    if not member.active:
        # 企微成员失效 → 停用平台用户（若 active）+ 撤销活动会话 + 安全审计（系统触发），fail closed。
        await wecom_identity.apply_member_status(
            session, user, member, trigger="oauth_callback", dry_run=False,
            actor_caller=None, trace_id=trace_id,
        )
        await session.commit()
        raise HTTPException(status_code=401, detail={"denied_reason": "wecom_user_inactive", "message": "企微成员已失效，账号已停用"})

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
    _set_session_cookie(response, raw_token, get_settings())
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


"""Enterprise WeChat OAuth and member identity clients; no drive access."""

from __future__ import annotations

import logging
import urllib.parse
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import safe_log_exception

_logger = logging.getLogger(__name__)


class WeComError(Exception):
    """企微调用失败（结构化，不含 secret/token/URL）。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        stage: str | None = None,
        http_status: int | None = None,
        upstream_errcode: int | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.stage = stage
        self.http_status = http_status
        self.upstream_errcode = upstream_errcode
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class WeComIdentity:
    """规范化企微身份（仅 wecom_user_id，绝不含 token/ticket）。"""

    wecom_user_id: str


@dataclass(frozen=True)
class WeComMemberStatus:
    """规范化企微成员生命周期状态。

    只承载业务层同步所需的规范化字段。`wecom_user_id` 为 server-only 关联键，**绝不**
    进 API 响应或审计。不会携带上游原始 payload / errmsg / token。
    """

    wecom_user_id: str  # server-only，不外泄
    active: bool
    status_code: str  # active / disabled / not_activated / deleted / unknown
    status_message: str  # 安全中文文案，非上游 errmsg
    name: str | None = None
    email: str | None = None
    avatar: str | None = None
    department_ids: tuple[str, ...] = ()


# 企微 user/get `status`：1 已激活 / 2 已禁用 / 4 未激活 / 5 退出企业。仅 1 视为有效。
_WECOM_STATUS_MAP = {
    1: ("active", True, "企微成员有效"),
    2: ("disabled", False, "企微成员已禁用"),
    4: ("not_activated", False, "企微成员未激活"),
    5: ("deleted", False, "企微成员已退出企业"),
}
# userid 不存在 / 不在通讯录可见范围（按已退出/无效处理）。
_WECOM_NOTFOUND_ERRCODES = {60111, 60121, 46004}


def _safe_errcode(data: dict[str, Any]) -> int | None:
    errcode = data.get("errcode")
    if isinstance(errcode, int):
        return errcode
    if isinstance(errcode, str):
        cleaned = errcode.strip()
        if cleaned.isdigit() and len(cleaned) <= 10:
            return int(cleaned)
    return None


def _oauth_exchange_log_extra(*, status: int, data: dict[str, Any]) -> dict[str, Any]:
    """OAuth identity response diagnostics with booleans only for identity fields."""
    return {
        "operation": "oauth_exchange",
        "status": status,
        "errcode": _safe_errcode(data),
        "has_userid": bool(data.get("userid")),
        "has_UserId": bool(data.get("UserId")),
        "has_openid": bool(data.get("openid")),
        "has_external_userid": bool(data.get("external_userid")),
        "has_user_ticket": bool(data.get("user_ticket")),
        "has_deviceid": bool(data.get("deviceid")),
        "has_corpid": bool(data.get("corpid")),
    }


def normalize_member_status(wecom_user_id: str, data: dict[str, Any]) -> WeComMemberStatus:
    """把企微 user/get 响应归一为安全 WeComMemberStatus（不回显原始 payload/errmsg）。

    读取成员生命周期与安全展示字段供服务端身份同步使用；未知状态一律 fail-closed。
    """
    try:
        errcode = int(data.get("errcode", 0) or 0)
    except (TypeError, ValueError):
        errcode = -1
    if errcode in _WECOM_NOTFOUND_ERRCODES:
        return WeComMemberStatus(wecom_user_id, False, "deleted", "企微成员不存在或已退出企业")
    if errcode != 0:
        return WeComMemberStatus(wecom_user_id, False, "unknown", "企微成员状态未知")
    try:
        status = int(data.get("status", 0) or 0)
    except (TypeError, ValueError):
        status = 0
    code, active, msg = _WECOM_STATUS_MAP.get(status, ("unknown", False, "企微成员状态未知"))
    name = str(data.get("name") or "").strip() or None
    email = str(data.get("email") or "").strip() or None
    avatar = str(data.get("avatar") or data.get("thumb_avatar") or "").strip() or None
    departments = data.get("department") or ()
    if not isinstance(departments, (list, tuple)):
        departments = ()
    department_ids = tuple(str(d).strip() for d in departments if str(d).strip())
    return WeComMemberStatus(
        wecom_user_id,
        active,
        code,
        msg,
        name=name,
        email=email,
        avatar=avatar,
        department_ids=department_ids,
    )


class WeComOAuthClient:
    """企微 OAuth 真实客户端（httpx）。失败只抛安全 WeComError。"""

    def __init__(
        self,
        *,
        corp_id: str,
        agent_id: str,
        app_secret: str,
        redirect_uri: str,
        base_url: str,
        timeout: float = 30.0,
    ) -> None:
        self._corp_id = corp_id
        self._agent_id = agent_id
        self._app_secret = app_secret
        self._redirect_uri = redirect_uri
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def build_authorize_url(self, *, state: str, mode: str = "client") -> str:
        """构造企微授权 URL（含 state）。不含 secret。"""
        if mode == "web_qr":
            params = {
                "appid": self._corp_id,
                "agentid": self._agent_id,
                "redirect_uri": self._redirect_uri,
                "state": state,
            }
            return "https://open.work.weixin.qq.com/wwopen/sso/qrConnect?" + urllib.parse.urlencode(
                params
            )
        params = {
            "appid": self._corp_id,
            "agentid": self._agent_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": "snsapi_base",
            "state": state,
        }
        return (
            "https://open.weixin.qq.com/connect/oauth2/authorize?"
            + urllib.parse.urlencode(params)
            + "#wechat_redirect"
        )

    @property
    def corp_id(self) -> str:
        """当前 OAuth 客户端绑定的可信企业 ID（服务端配置）。"""
        return self._corp_id

    async def _access_token(self, client: httpx.AsyncClient) -> str:
        resp = await client.get(
            f"{self._base}/cgi-bin/gettoken",
            params={"corpid": self._corp_id, "corpsecret": self._app_secret},
        )
        data = self._safe_json(resp)
        token = data.get("access_token")
        if not token:
            # 不回显上游 errmsg（可能含敏感串）。
            raise WeComError("wecom_token_failed", "企微 access_token 获取失败")
        return str(token)

    async def exchange_code(self, code: str) -> WeComIdentity:
        """用 OAuth code 换规范化身份。access_token / code 绝不外泄/持久化。"""
        if not code:
            raise WeComError("wecom_missing_code", "缺少授权 code")
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                token = await self._access_token(client)
                resp = await client.get(
                    f"{self._base}/cgi-bin/auth/getuserinfo",
                    params={"access_token": token, "code": code},
                )
                data = self._safe_json(resp)
        except httpx.HTTPError as exc:
            raise WeComError(
                "wecom_network_error", f"企微网络错误（{type(exc).__name__}）"
            ) from exc
        # 仅记安全诊断 metadata；绝不记 code / access_token / userid / secret / errmsg。
        _logger.info(
            "wecom_call", extra=_oauth_exchange_log_extra(status=resp.status_code, data=data)
        )
        user_id = data.get("userid") or data.get("UserId")
        if not user_id:
            raise WeComError("wecom_userinfo_failed", "企微身份解析失败（非企业成员或无 userid）")
        return WeComIdentity(wecom_user_id=str(user_id))

    async def get_member_status(
        self, wecom_user_id: str
    ) -> WeComMemberStatus:  # pragma: no cover - 真实网络
        """查企微成员生命周期与安全同步字段。失败只抛安全 WeComError。"""
        if not wecom_user_id:
            raise WeComError("wecom_missing_userid", "缺少企微成员标识")
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                token = await self._access_token(client)
                resp = await client.get(
                    f"{self._base}/cgi-bin/user/get",
                    params={"access_token": token, "userid": wecom_user_id},
                )
                data = self._safe_json(resp)
        except httpx.HTTPError as exc:
            raise WeComError(
                "wecom_network_error", f"企微网络错误（{type(exc).__name__}）"
            ) from exc
        _logger.info("wecom_call", extra={"operation": "member_status", "status": resp.status_code})
        return normalize_member_status(wecom_user_id, data)

    @staticmethod
    def _safe_json(resp: httpx.Response) -> dict[str, Any]:
        try:
            result: dict[str, Any] = resp.json()
            return result
        except Exception as exc:  # noqa: BLE001
            safe_log_exception(_logger, "wecom_response_not_json", exc, status=resp.status_code)
            raise WeComError("wecom_bad_response", "企微响应解析失败") from exc


class NullWeComOAuthClient:
    def build_authorize_url(self, *, state: str, mode: str = "client") -> str:
        raise WeComError("wecom_not_configured", "企微 OAuth 未配置")

    async def exchange_code(self, code: str) -> WeComIdentity:
        raise WeComError("wecom_not_configured", "企微 OAuth 未配置")

    async def get_member_status(self, wecom_user_id: str) -> WeComMemberStatus:
        raise WeComError("wecom_not_configured", "企微 OAuth 未配置")


def wecom_enabled() -> bool:
    s = get_settings()
    return bool(s.wecom_corp_id and s.wecom_app_secret)


def get_wecom_oauth_client() -> WeComOAuthClient | NullWeComOAuthClient:
    """FastAPI 依赖：配置齐全 → 真实 OAuth 客户端；否则 Null。测试经依赖覆盖注入 fake。"""
    if not wecom_enabled():
        return NullWeComOAuthClient()
    s = get_settings()
    return WeComOAuthClient(
        corp_id=s.wecom_corp_id,
        agent_id=s.wecom_agent_id,
        app_secret=s.wecom_app_secret,
        redirect_uri=s.wecom_redirect_uri,
        base_url=s.wecom_api_base_url,
        timeout=s.wecom_timeout,
    )

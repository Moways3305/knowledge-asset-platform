"""企业微信客户端抽象。

两个窄客户端，把企微细节隔离在此，业务层只消费**规范化结果**：
- `WeComOAuthClient`：构造授权 URL、用 code 换取规范化身份 `{wecom_user_id}`。
- `WeComDriveClient`：列目录文件（安全元数据）、按 file_id 下载字节。

安全红线：
- `app_secret` / `access_token` / `code` / 临时下载 URL **绝不**进异常 / 日志 / 审计 / 响应。
- `WeComError` 只带安全 code/message，不回显上游原始 payload（可能含 token/URL）。
- 规范化结果只暴露稳定安全字段：wecom_user_id / file_id（server-only）/ name / mime / size /
  content_hash；**不暴露**临时下载 URL / token。

dev/降级：未配置（corp_id/app_secret 缺）→ `*_enabled()` False，依赖返回 Null 客户端
（调用抛 `wecom_not_configured`）。测试经依赖覆盖注入 fake，不打真实网络。
"""

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


@dataclass(frozen=True)
class WeComDriveFile:
    """规范化微盘文件元数据。file_id 为 server-only 稳定标识，不外泄前端/响应。"""

    file_id: str
    name: str
    mime: str | None
    size: int | None
    content_hash: str | None


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


# 常见扩展名 → mime（list 仅给元数据，下载前据此标注；未知 → None）。
_EXT_MIME = {
    "txt": "text/plain",
    "md": "text/markdown",
    "csv": "text/csv",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
}


def _guess_mime(name: str) -> str | None:
    ext = name.rsplit(".", 1)[1].lower() if "." in (name or "") else ""
    return _EXT_MIME.get(ext)


def parse_directory_path(directory_path: str) -> tuple[str, str]:
    """解析配置的 directory_path → (spaceid, fatherid)。

    **文档化内部格式**：`spaceid:<id>;fatherid:<id>`（两个均为企微微盘内部标识，server-only，
    绝不外泄）。fatherid 省略时为根目录（空串）。格式非法 → WeComError，不静默用 admin/系统。
    """
    parts = dict(kv.split(":", 1) for kv in (directory_path or "").split(";") if ":" in kv)
    spaceid = (parts.get("spaceid") or "").strip()
    fatherid = (parts.get("fatherid") or "").strip()
    if not spaceid:
        raise WeComError(
            "wecom_invalid_directory",
            "扫描目录格式应为 'spaceid:<id>;fatherid:<id>'（缺少 spaceid）",
        )
    return spaceid, fatherid


class WeComDriveClient:
    """企微微盘真实客户端（httpx）。返回规范化元数据 / 字节，不暴露临时 URL/token/cookie。

    端点（官方微盘 API，base `${WECOM_DRIVE_BASE_URL}`）：
    - 列举：`POST /cgi-bin/wedrive/file_list?access_token=...`（body 含 spaceid/fatherid/start/limit，翻页）。
    - 下载：`POST /cgi-bin/wedrive/file_download?access_token=...` → 返回临时 `download_url` +
      `cookie_name/value`；随后**后端**带 cookie GET 该 URL 取字节。download_url / cookie / token
      全程仅在本客户端内部使用，**绝不**返回/持久化/审计/日志。
    """

    def __init__(
        self,
        *,
        corp_id: str,
        app_secret: str,
        base_url: str,
        page_size: int = 100,
        timeout: float = 30.0,
    ) -> None:
        self._corp_id = corp_id
        self._app_secret = app_secret
        self._base = base_url.rstrip("/")
        self._page_size = max(1, min(page_size, 1000))
        self._timeout = timeout

    _TOKEN_ERRCODES = {40001, 40014, 41001, 42001, 42007, 42009}
    _PERMISSION_ERRCODES = {48002, 60011, 60020, 301002, 301005}

    @classmethod
    def _check(cls, data: dict[str, Any], *, stage: str = "unknown") -> dict[str, Any]:
        """校验 HTTP 200 的企微业务响应，保留安全 errcode 元数据但不回显 errmsg。"""
        raw_errcode = data.get("errcode", 0)
        try:
            errcode = int(raw_errcode or 0)
        except (TypeError, ValueError):
            raise WeComError("wecom_drive_bad_response", "企微响应格式异常", stage=stage) from None
        if errcode in cls._TOKEN_ERRCODES:
            raise WeComError(
                "wecom_token_rejected",
                "企微访问令牌无效或已过期",
                stage=stage,
                upstream_errcode=errcode,
            )
        if errcode in cls._PERMISSION_ERRCODES:
            raise WeComError(
                "wecom_drive_permission_denied",
                "企业微信应用或成员无微盘访问权限",
                stage=stage,
                upstream_errcode=errcode,
            )
        if errcode != 0:
            raise WeComError(
                "wecom_drive_upstream_rejected",
                "企业微信微盘拒绝了请求",
                stage=stage,
                upstream_errcode=errcode,
            )
        return data

    @staticmethod
    def _response_json(resp: httpx.Response, *, stage: str) -> dict[str, Any]:
        if resp.status_code < 200 or resp.status_code >= 300:
            raise WeComError(
                "wecom_drive_http_error",
                "企业微信微盘 HTTP 请求失败",
                stage=stage,
                http_status=resp.status_code,
            )
        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise WeComError(
                "wecom_drive_bad_response",
                "企业微信微盘返回了不可解析的响应",
                stage=stage,
                http_status=resp.status_code,
            ) from exc
        if not isinstance(data, dict):
            raise WeComError(
                "wecom_drive_bad_response",
                "企业微信微盘响应格式异常",
                stage=stage,
                http_status=resp.status_code,
            )
        return data

    async def _access_token(self, client: httpx.AsyncClient) -> str:
        try:
            resp = await client.get(
                f"{self._base}/cgi-bin/gettoken",
                params={"corpid": self._corp_id, "corpsecret": self._app_secret},
            )
        except httpx.HTTPError as exc:
            raise WeComError(
                "wecom_drive_network_unavailable",
                "企业微信网络连接失败",
                stage="token",
            ) from exc
        data = self._check(self._response_json(resp, stage="token"), stage="token")
        token = data.get("access_token")
        if not isinstance(token, str) or not token.strip():
            raise WeComError(
                "wecom_token_missing",
                "企业微信未返回访问令牌",
                stage="token",
                http_status=resp.status_code,
            )
        return str(token)

    async def _post_json(
        self,
        client: httpx.AsyncClient,
        *,
        path: str,
        token: str,
        body: dict[str, Any],
        stage: str,
    ) -> dict[str, Any]:
        try:
            resp = await client.post(
                f"{self._base}{path}",
                params={"access_token": token},
                json=body,
            )
        except httpx.HTTPError as exc:
            raise WeComError(
                "wecom_drive_network_unavailable",
                "企业微信网络连接失败",
                stage=stage,
            ) from exc
        return self._check(self._response_json(resp, stage=stage), stage=stage)

    async def create_project_space(
        self, *, space_name: str, manager_user_ids: list[str]
    ) -> str:  # pragma: no cover - 真实网络
        """按企业微信官方 `space_create` 契约创建一项目一共享空间。

        官方文档：https://developer.work.weixin.qq.com/document/path/93655
        应用本身是创建者；有效项目经理以 auth=7（应用空间管理员）加入，最多 3 人。
        """
        if len(manager_user_ids) > 3:
            raise WeComError(
                "wecom_space_manager_limit",
                "项目有效经理超过企业微信空间管理员上限",
                stage="space_create",
            )
        body: dict[str, Any] = {
            "space_name": space_name,
            "auth_info": [
                {"type": 1, "userid": user_id, "auth": 7} for user_id in manager_user_ids
            ],
            "space_sub_type": 0,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            token = await self._access_token(client)
            data = await self._post_json(
                client,
                path="/cgi-bin/wedrive/space_create",
                token=token,
                body=body,
                stage="space_create",
            )
        space_id = data.get("spaceid")
        if not isinstance(space_id, str) or not space_id.strip():
            raise WeComError(
                "wecom_drive_bad_response",
                "企业微信未返回空间标识",
                stage="space_create",
            )
        return space_id.strip()

    async def list_files(
        self, directory_path: str
    ) -> list[WeComDriveFile]:  # pragma: no cover - 真实网络
        """翻页列举目录文件，规范化为 WeComDriveFile（仅安全元数据）。"""
        spaceid, fatherid = parse_directory_path(directory_path)
        out: list[WeComDriveFile] = []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            token = await self._access_token(client)
            pending_directories = [fatherid]
            visited_directories: set[str] = set()
            while pending_directories:
                current_fatherid = pending_directories.pop(0)
                if current_fatherid in visited_directories:
                    continue
                visited_directories.add(current_fatherid)
                start = 0
                while True:
                    data = await self._post_json(
                        client,
                        path="/cgi-bin/wedrive/file_list",
                        token=token,
                        body={
                            "spaceid": spaceid,
                            "fatherid": current_fatherid,
                            "sort_type": 1,
                            "start": start,
                            "limit": self._page_size,
                        },
                        stage="file_list",
                    )
                    for it in data.get("file_list") or []:
                        if not isinstance(it, dict):
                            continue
                        fid = it.get("fileid") or it.get("file_id")
                        name = it.get("file_name") or it.get("name") or ""
                        if not fid or not name:
                            continue
                        if str(it.get("file_type")) == "1" or bool(it.get("is_dir")):
                            pending_directories.append(str(fid))
                            continue
                        out.append(
                            WeComDriveFile(
                                file_id=str(fid),
                                name=str(name),
                                mime=_guess_mime(str(name)),
                                size=it.get("file_size") or it.get("size"),
                                content_hash=it.get("sha") or it.get("file_sha") or None,
                            )
                        )
                    if not data.get("has_more"):
                        break
                    start = int(data.get("next_start") or (start + self._page_size))
        return out

    async def download_file(self, file_id: str) -> bytes:  # pragma: no cover - 真实网络
        """两步下载：换临时 URL+cookie → 后端带 cookie GET 取字节。URL/cookie 不外泄。"""
        if not file_id:
            raise WeComError("wecom_missing_file_id", "缺少 file_id")
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                token = await self._access_token(client)
                data = await self._post_json(
                    client,
                    path="/cgi-bin/wedrive/file_download",
                    token=token,
                    body={"fileid": file_id},
                    stage="file_download",
                )
                download_url = data.get("download_url")
                if not download_url:
                    raise WeComError(
                        "wecom_drive_bad_response",
                        "企微微盘未返回下载地址",
                        stage="file_download",
                    )
                headers = {}
                cookie_name = data.get("cookie_name")
                cookie_value = data.get("cookie_value")
                if cookie_name and cookie_value:
                    headers["Cookie"] = f"{cookie_name}={cookie_value}"
                file_resp = await client.get(download_url, headers=headers)
                if file_resp.status_code >= 400:
                    # 不回显 download_url / 状态体（可能含临时签名）。
                    raise WeComError(
                        "wecom_drive_http_error",
                        "企微微盘文件下载失败",
                        stage="file_download",
                        http_status=file_resp.status_code,
                    )
                return file_resp.content
        except httpx.HTTPError as exc:
            raise WeComError(
                "wecom_drive_network_unavailable",
                "企业微信网络连接失败",
                stage="file_download",
            ) from exc


class NullWeComOAuthClient:
    def build_authorize_url(self, *, state: str, mode: str = "client") -> str:
        raise WeComError("wecom_not_configured", "企微 OAuth 未配置")

    async def exchange_code(self, code: str) -> WeComIdentity:
        raise WeComError("wecom_not_configured", "企微 OAuth 未配置")

    async def get_member_status(self, wecom_user_id: str) -> WeComMemberStatus:
        raise WeComError("wecom_not_configured", "企微 OAuth 未配置")


class NullWeComDriveClient:
    async def list_files(self, directory_path: str) -> list[WeComDriveFile]:
        raise WeComError("wecom_not_configured", "企微微盘未配置")

    async def download_file(self, file_id: str) -> bytes:
        raise WeComError("wecom_not_configured", "企微微盘未配置")

    async def create_project_space(self, *, space_name: str, manager_user_ids: list[str]) -> str:
        raise WeComError("wecom_not_configured", "企微微盘未配置")


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
        base_url=s.wecom_drive_base_url,
        timeout=s.wecom_timeout,
    )


def get_wecom_drive_client() -> WeComDriveClient | NullWeComDriveClient:
    if not wecom_enabled():
        return NullWeComDriveClient()
    s = get_settings()
    return WeComDriveClient(
        corp_id=s.wecom_corp_id,
        app_secret=s.wecom_app_secret,
        base_url=s.wecom_drive_base_url,
        page_size=s.wecom_scan_page_size,
        timeout=s.wecom_timeout,
    )

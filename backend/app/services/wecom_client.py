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

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
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


@dataclass(frozen=True)
class WeComDriveSpace:
    """规范化微盘空间。space_ref 为 admin 配置 UI 可用的稳定选择引用。"""

    space_ref: str
    name: str


@dataclass(frozen=True)
class WeComDriveDirectory:
    """规范化微盘目录节点。directory_ref 即可保存的配置串 `spaceid:<id>;fatherid:<id>`。

    只承载**目录选择**所需安全字段；绝不含普通文件 file_id / download_url / token / cookie。
    """

    directory_ref: str
    name: str
    parent_ref: str | None
    has_children: bool | None


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

    @staticmethod
    def _check(data: dict[str, Any]) -> dict[str, Any]:
        """校验微盘响应 errcode；非 0 抛安全 WeComError（只带 errcode，不回显 errmsg 原文）。"""
        errcode = data.get("errcode", 0)
        if errcode and int(errcode) != 0:
            raise WeComError(f"wecom_api_{int(errcode)}", "企微微盘接口返回错误")
        return data

    async def _access_token(self, client: httpx.AsyncClient) -> str:
        resp = await client.get(
            f"{self._base}/cgi-bin/gettoken",
            params={"corpid": self._corp_id, "corpsecret": self._app_secret},
        )
        data = WeComOAuthClient._safe_json(resp)
        token = data.get("access_token")
        if not token:
            raise WeComError("wecom_token_failed", "企微 access_token 获取失败")
        return str(token)

    async def list_files(
        self, directory_path: str
    ) -> list[WeComDriveFile]:  # pragma: no cover - 真实网络
        """翻页列举目录文件，规范化为 WeComDriveFile（仅安全元数据）。"""
        spaceid, fatherid = parse_directory_path(directory_path)
        out: list[WeComDriveFile] = []
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                token = await self._access_token(client)
                start = 0
                while True:
                    resp = await client.post(
                        f"{self._base}/cgi-bin/wedrive/file_list",
                        params={"access_token": token},
                        json={
                            "spaceid": spaceid,
                            "fatherid": fatherid,
                            "sort_type": 1,
                            "start": start,
                            "limit": self._page_size,
                        },
                    )
                    data = self._check(WeComOAuthClient._safe_json(resp))
                    for it in data.get("file_list") or []:
                        if not isinstance(it, dict):
                            continue
                        fid = it.get("fileid") or it.get("file_id")
                        name = it.get("file_name") or it.get("name") or ""
                        if not fid or not name:
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
        except httpx.HTTPError as exc:
            raise WeComError(
                "wecom_network_error", f"企微网络错误（{type(exc).__name__}）"
            ) from exc
        return out

    # ---- 目录浏览（只列空间 / 目录，不列普通文件，不下载）----
    @staticmethod
    def _to_spaces(raw_items: Any) -> list[WeComDriveSpace]:
        """把上游空间列表归一为安全 DTO（只取 spaceid/name）。"""
        out: list[WeComDriveSpace] = []
        for it in raw_items or []:
            if not isinstance(it, dict):
                continue
            sid = it.get("spaceid") or it.get("space_id")
            name = it.get("space_name") or it.get("name") or ""
            if not sid:
                continue
            out.append(WeComDriveSpace(space_ref=str(sid), name=str(name or sid)))
        return out

    @staticmethod
    def _to_directories(spaceid: str, raw_items: Any) -> list[WeComDriveDirectory]:
        """把上游 file_list 归一为安全目录 DTO：**仅保留目录节点**，普通文件全部丢弃。

        directory_ref = 可直接保存的配置串 `spaceid:<id>;fatherid:<folderid>`。绝不外泄上游
        download_url / cookie / token / 普通文件 file_id / 原始 payload。
        """
        out: list[WeComDriveDirectory] = []
        for it in raw_items or []:
            if not isinstance(it, dict):
                continue
            # 微盘 file_type=1 为文件夹；兼容 is_dir 布尔。仅目录入选。
            is_dir = str(it.get("file_type")) == "1" or bool(it.get("is_dir"))
            if not is_dir:
                continue
            fid = it.get("fileid") or it.get("file_id")
            name = it.get("file_name") or it.get("name") or ""
            if not fid or not name:
                continue
            out.append(
                WeComDriveDirectory(
                    directory_ref=f"spaceid:{spaceid};fatherid:{fid}",
                    name=str(name),
                    parent_ref=None,
                    has_children=None,
                )
            )
        return out

    async def list_spaces(self) -> list[WeComDriveSpace]:  # pragma: no cover - 真实网络
        """列当前企业可见的微盘空间（仅安全选择元数据）。"""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                token = await self._access_token(client)
                resp = await client.post(
                    f"{self._base}/cgi-bin/wedrive/space_list",
                    params={"access_token": token},
                    json={},
                )
                data = self._check(WeComOAuthClient._safe_json(resp))
        except httpx.HTTPError as exc:
            raise WeComError(
                "wecom_network_error", f"企微网络错误（{type(exc).__name__}）"
            ) from exc
        return self._to_spaces(data.get("space_list") or data.get("spaces"))

    async def list_directories(  # pragma: no cover - 真实网络
        self, space_ref: str, parent_ref: str | None = None
    ) -> list[WeComDriveDirectory]:
        """列某空间/父目录下的**子目录**（不含普通文件）。space_ref=spaceid，parent_ref=fatherid。"""
        spaceid = (space_ref or "").strip()
        if not spaceid:
            raise WeComError("wecom_invalid_space", "缺少微盘空间标识")
        fatherid = (parent_ref or "").strip()
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                token = await self._access_token(client)
                resp = await client.post(
                    f"{self._base}/cgi-bin/wedrive/file_list",
                    params={"access_token": token},
                    json={
                        "spaceid": spaceid,
                        "fatherid": fatherid,
                        "sort_type": 1,
                        "start": 0,
                        "limit": self._page_size,
                    },
                )
                data = self._check(WeComOAuthClient._safe_json(resp))
        except httpx.HTTPError as exc:
            raise WeComError(
                "wecom_network_error", f"企微网络错误（{type(exc).__name__}）"
            ) from exc
        return self._to_directories(spaceid, data.get("file_list"))

    async def download_file(self, file_id: str) -> bytes:  # pragma: no cover - 真实网络
        """两步下载：换临时 URL+cookie → 后端带 cookie GET 取字节。URL/cookie 不外泄。"""
        if not file_id:
            raise WeComError("wecom_missing_file_id", "缺少 file_id")
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                token = await self._access_token(client)
                resp = await client.post(
                    f"{self._base}/cgi-bin/wedrive/file_download",
                    params={"access_token": token},
                    json={"fileid": file_id},
                )
                data = self._check(WeComOAuthClient._safe_json(resp))
                download_url = data.get("download_url")
                if not download_url:
                    raise WeComError("wecom_download_no_url", "企微微盘未返回下载地址")
                headers = {}
                cookie_name = data.get("cookie_name")
                cookie_value = data.get("cookie_value")
                if cookie_name and cookie_value:
                    headers["Cookie"] = f"{cookie_name}={cookie_value}"
                file_resp = await client.get(download_url, headers=headers)
                if file_resp.status_code >= 400:
                    # 不回显 download_url / 状态体（可能含临时签名）。
                    raise WeComError("wecom_download_failed", "企微微盘文件下载失败")
                return file_resp.content
        except httpx.HTTPError as exc:
            raise WeComError(
                "wecom_network_error", f"企微网络错误（{type(exc).__name__}）"
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

    async def list_spaces(self) -> list[WeComDriveSpace]:
        raise WeComError("wecom_not_configured", "企微微盘未配置")

    async def list_directories(
        self, space_ref: str, parent_ref: str | None = None
    ) -> list[WeComDriveDirectory]:
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

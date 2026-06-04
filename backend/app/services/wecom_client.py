"""企业微信客户端抽象（R6）。

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

import urllib.parse
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings


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
class WeComDriveFile:
    """规范化微盘文件元数据。file_id 为 server-only 稳定标识，不外泄前端/响应。"""

    file_id: str
    name: str
    mime: str | None
    size: int | None
    content_hash: str | None


class WeComOAuthClient:
    """企微 OAuth 真实客户端（httpx）。失败只抛安全 WeComError。"""

    def __init__(self, *, corp_id: str, agent_id: str, app_secret: str, redirect_uri: str,
                 base_url: str, timeout: float = 30.0) -> None:
        self._corp_id = corp_id
        self._agent_id = agent_id
        self._app_secret = app_secret
        self._redirect_uri = redirect_uri
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def build_authorize_url(self, *, state: str) -> str:
        """构造企微授权 URL（含 state）。不含 secret。"""
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
            raise WeComError("wecom_network_error", f"企微网络错误（{type(exc).__name__}）") from exc
        user_id = data.get("userid") or data.get("UserId")
        if not user_id:
            raise WeComError("wecom_userinfo_failed", "企微身份解析失败（非企业成员或无 userid）")
        return WeComIdentity(wecom_user_id=str(user_id))

    @staticmethod
    def _safe_json(resp: httpx.Response) -> dict[str, Any]:
        try:
            return resp.json()
        except Exception as exc:  # noqa: BLE001
            raise WeComError("wecom_bad_response", "企微响应解析失败") from exc


# 常见扩展名 → mime（list 仅给元数据，下载前据此标注；未知 → None）。
_EXT_MIME = {
    "txt": "text/plain", "md": "text/markdown", "csv": "text/csv",
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
    parts = dict(
        kv.split(":", 1) for kv in (directory_path or "").split(";") if ":" in kv
    )
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

    def __init__(self, *, corp_id: str, app_secret: str, base_url: str,
                 page_size: int = 100, timeout: float = 30.0) -> None:
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

    async def list_files(self, directory_path: str) -> list[WeComDriveFile]:  # pragma: no cover - 真实网络
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
                            "spaceid": spaceid, "fatherid": fatherid,
                            "sort_type": 1, "start": start, "limit": self._page_size,
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
            raise WeComError("wecom_network_error", f"企微网络错误（{type(exc).__name__}）") from exc
        return out

    async def download_file(self, file_id: str) -> bytes:  # pragma: no cover - 真实网络
        """两步下载：换临时 URL+cookie → 后端带 cookie GET 取字节。URL/cookie 不外泄。"""
        if not file_id:
            raise WeComError("wecom_missing_file_id", "缺少 file_id")
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                token = await self._access_token(client)
                resp = await client.post(
                    f"{self._base}/cgi-bin/wedrive/file_download",
                    params={"access_token": token}, json={"fileid": file_id},
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
            raise WeComError("wecom_network_error", f"企微网络错误（{type(exc).__name__}）") from exc


class NullWeComOAuthClient:
    def build_authorize_url(self, *, state: str) -> str:
        raise WeComError("wecom_not_configured", "企微 OAuth 未配置")

    async def exchange_code(self, code: str) -> WeComIdentity:
        raise WeComError("wecom_not_configured", "企微 OAuth 未配置")


class NullWeComDriveClient:
    async def list_files(self, directory_path: str) -> list[WeComDriveFile]:
        raise WeComError("wecom_not_configured", "企微微盘未配置")

    async def download_file(self, file_id: str) -> bytes:
        raise WeComError("wecom_not_configured", "企微微盘未配置")


def wecom_enabled() -> bool:
    s = get_settings()
    return bool(s.wecom_corp_id and s.wecom_app_secret)


def get_wecom_oauth_client() -> "WeComOAuthClient | NullWeComOAuthClient":
    """FastAPI 依赖：配置齐全 → 真实 OAuth 客户端；否则 Null。测试经依赖覆盖注入 fake。"""
    if not wecom_enabled():
        return NullWeComOAuthClient()
    s = get_settings()
    return WeComOAuthClient(
        corp_id=s.wecom_corp_id, agent_id=s.wecom_agent_id, app_secret=s.wecom_app_secret,
        redirect_uri=s.wecom_redirect_uri, base_url=s.wecom_drive_base_url, timeout=s.wecom_timeout,
    )


def get_wecom_drive_client() -> "WeComDriveClient | NullWeComDriveClient":
    if not wecom_enabled():
        return NullWeComDriveClient()
    s = get_settings()
    return WeComDriveClient(
        corp_id=s.wecom_corp_id, app_secret=s.wecom_app_secret,
        base_url=s.wecom_drive_base_url, page_size=s.wecom_scan_page_size, timeout=s.wecom_timeout,
    )

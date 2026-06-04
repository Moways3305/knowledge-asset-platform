"""ONLYOFFICE 只读预览适配器（R7）。

把"平台受控预览元数据 → Document Server 编辑器配置"的拼装隔离在此。只生成**只读**
（view 模式、禁编辑/下载/打印）配置；Document Server 通过我们下发的**受控取件 URL**
回取文件字节（带短时不透明 token），平台据此渲染，绝不暴露对象存储 URL / storage_ref。

安全红线：
- `ONLYOFFICE_JWT_SECRET` 只用于签名 config，**绝不**进响应 / 日志 / 审计 / 用户可见记录；
  签出的 JWT 是不透明串（HS256）。
- 配置里只含：安全标题、文件类型、文档 key、受控取件 URL（含短时 token）；
  **不含** storage_ref / source_file_ref / 对象存储 URL / 完整凭证 token / WeKnora id。
- 未配置/不支持类型 → 安全错误（onlyoffice_not_configured / preview_type_not_available），
  绝不回退泄露原文 URL。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

from app.core.config import get_settings


class OnlyOfficeError(Exception):
    """ONLYOFFICE 适配失败（结构化，不含 jwt_secret / 内部路径）。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


# 扩展名 → (ONLYOFFICE fileType, documentType)。仅常见办公文档；未知 → 不支持。
_DOC_TYPES = {
    "docx": ("docx", "word"), "doc": ("doc", "word"), "txt": ("txt", "word"),
    "md": ("txt", "word"), "rtf": ("rtf", "word"), "odt": ("odt", "word"),
    "pdf": ("pdf", "word"),
    "xlsx": ("xlsx", "cell"), "xls": ("xls", "cell"), "csv": ("csv", "cell"),
    "pptx": ("pptx", "slide"), "ppt": ("ppt", "slide"),
}


def onlyoffice_enabled() -> bool:
    s = get_settings()
    return bool(s.onlyoffice_enabled and s.onlyoffice_document_server_url)


def resolve_doc_type(file_name: str) -> tuple[str, str] | None:
    """按文件名扩展名解析 ONLYOFFICE (fileType, documentType)；不支持 → None。"""
    ext = file_name.rsplit(".", 1)[1].lower() if "." in (file_name or "") else ""
    return _DOC_TYPES.get(ext)


def _sign_hs256(payload: dict, secret: str) -> str:
    """最小 HS256 JWT 签名（不引第三方依赖）。secret 不出现在返回值里（仅签名）。"""
    def _b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode())
    signing_input = f"{header}.{body}".encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header}.{body}.{_b64(sig)}"


def build_view_config(
    *,
    document_key: str,
    document_title: str,
    file_name: str,
    fetch_url: str,
    document_server_url: str | None = None,
) -> dict:
    """生成只读预览的 ONLYOFFICE 编辑器配置（含受控取件 URL）。

    `fetch_url` 是平台受控取件地址（含短时 token），由 Document Server 回取字节。
    若配置了 jwt_secret，则附 HS256 `token`（不透明）；secret 本身不进配置。
    """
    if not onlyoffice_enabled():
        raise OnlyOfficeError("onlyoffice_not_configured", "ONLYOFFICE 未配置")
    doc_type = resolve_doc_type(file_name)
    if doc_type is None:
        raise OnlyOfficeError("preview_type_not_available", "该文件类型暂不支持预览")
    file_type, document_type = doc_type

    s = get_settings()
    config: dict = {
        "documentServerUrl": document_server_url or s.onlyoffice_document_server_url,
        "documentType": document_type,
        "document": {
            "title": document_title,
            "fileType": file_type,
            "key": document_key,  # 文档版本 key（同内容稳定，安全派生，非 storage_ref）
            "url": fetch_url,
            "permissions": {  # 只读：禁编辑/下载/打印/复制
                "edit": False, "download": False, "print": False,
                "copy": False, "review": False,
            },
        },
        "editorConfig": {
            "mode": "view",
            "customization": {"chat": False, "comments": False, "help": False},
        },
    }
    if s.onlyoffice_jwt_secret:
        # JWT 仅签名 config 内容；secret 不入 config。
        config["token"] = _sign_hs256(config, s.onlyoffice_jwt_secret)
    return config

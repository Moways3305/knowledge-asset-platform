"""预览凭证 API 的请求 / 响应 schema（IMPLEMENT-07）。

**绝不返回**完整 token 明文、对象存储真实路径 / 签名 URL、文件内部存储引用、bucket。
preview_entry_url 是平台受控相对路径。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class PreviewIssueRequest(BaseModel):
    version_id: uuid.UUID | None = None


class PreviewIssueResponse(BaseModel):
    credential_id: uuid.UUID
    preview_type: str
    credential_fingerprint: str
    preview_entry_url: str
    expires_at: datetime
    credential_status: str


class PreviewEntryResponse(BaseModel):
    """平台受控预览入口返回（R7：真实 ONLYOFFICE 只读预览配置）。

    onlyoffice_config 含 Document Server 编辑器配置 + 平台受控取件 URL（含短时 token）；
    **绝不**含内部存储引用 / 源文件引用 / 对象存储 URL / 完整凭证 token / jwt 密钥 /
    WeKnora id。未配置 / 不支持类型 / 无可用源 时 onlyoffice_config 为 None，message 给安全说明。
    """

    credential_id: uuid.UUID
    target_asset_id: uuid.UUID
    preview_type: str
    document_title: str
    credential_fingerprint: str
    expires_at: datetime
    credential_status: str
    onlyoffice_config: dict | None = None
    message: str | None = None

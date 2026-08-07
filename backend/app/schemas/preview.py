"""预览凭证 API 的请求 / 响应 schema。

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
    """平台受控预览入口返回（按文件类型分发渲染方式）。

    - render_type：pdf / image / markdown / text / office——前端据此选择渲染器；
    - file_url：平台受控取件相对路径（含短时 fetch token，仅凭证有效期内可读），
      供浏览器内嵌（PDF 查看器 / 图片 / 文本读取）使用；
    - onlyoffice_config：render_type=office 时含 Document Server 编辑器配置 + 平台受控取件 URL；
    **绝不**含内部存储引用 / 源文件引用 / 对象存储 URL / 完整凭证 token / jwt 密钥 /
    WeKnora id。未配置 / 不支持类型 / 无可用源 时对应字段为 None，message 给安全说明。
    """

    credential_id: uuid.UUID
    target_asset_id: uuid.UUID
    preview_type: str
    document_title: str
    credential_fingerprint: str
    expires_at: datetime
    credential_status: str
    render_type: str | None = None
    file_url: str | None = None
    onlyoffice_config: dict | None = None
    message: str | None = None

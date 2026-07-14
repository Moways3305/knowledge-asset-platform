"""公司知识库生命周期 API 的安全请求/响应。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class CompanyKbCreateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=100)

    @field_validator("display_name")
    @classmethod
    def _strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("display_name 不能为空白")
        return cleaned


class CompanyKbOut(BaseModel):
    """不含底座 KB/model id、URL、密钥或存储引用的安全状态。"""

    exists: bool
    display_name: str | None = None
    status: str | None = None
    created_at: datetime | None = None
    available: bool = False
    availability_summary: str

"""KAP 内容生成模型 API schema。

管理写请求中的 API 地址/API key 只单向上送；所有响应仅含安全展示字段。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, SecretStr


class GenerationModelOptionOut(BaseModel):
    model_ref: str
    display_name: str
    provider: str
    model_name: str
    enabled: bool = True
    is_default: bool = False


class GenerationModelOptionsResponse(BaseModel):
    items: list[GenerationModelOptionOut]
    default_missing: bool = True


class GenerationModelAdminListResponse(BaseModel):
    items: list[GenerationModelOptionOut]
    total: int


class GenerationModelCreateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    provider: str = Field(min_length=1, max_length=50)
    model_name: str = Field(min_length=1, max_length=200)
    base_url: SecretStr
    api_key: SecretStr
    enabled: bool = True
    make_default: bool = False


class GenerationModelUpdateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    provider: str = Field(min_length=1, max_length=50)
    model_name: str = Field(min_length=1, max_length=200)
    # 空值表示保持已保存的敏感配置不变。
    base_url: SecretStr | None = None
    api_key: SecretStr | None = None
    enabled: bool = True


class GenerationModelSelectionRequest(BaseModel):
    model_ref: str | None = None


class GenerationModelSelectionResponse(BaseModel):
    current_default: GenerationModelOptionOut | None = None
    configured: bool = False


class GenerationModelDeleteResponse(BaseModel):
    deleted: bool = True


class GenerationModelTestResponse(BaseModel):
    success: bool
    message: str
    duration_ms: int


class GenerationModelAdminOut(GenerationModelOptionOut):
    updated_at: datetime | None = None

"""KAP 内容生成模型 API schema。"""

from __future__ import annotations

from pydantic import BaseModel


class GenerationModelOptionOut(BaseModel):
    model_ref: str
    name: str
    provider: str | None = None
    enabled: bool = True
    is_default: bool = False


class GenerationModelOptionsResponse(BaseModel):
    items: list[GenerationModelOptionOut]
    default_missing: bool = True


class GenerationModelSelectionRequest(BaseModel):
    model_ref: str | None = None


class GenerationModelSelectionResponse(BaseModel):
    current_default: GenerationModelOptionOut | None = None
    configured: bool = False

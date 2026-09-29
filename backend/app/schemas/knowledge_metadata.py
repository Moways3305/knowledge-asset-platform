"""Explicit, concurrency-checked metadata edits; never accept ownership or storage fields."""

from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.enums import AssetType, ConfidentialityLevel


class KnowledgeMetadataResult(BaseModel):
    asset_id: UUID
    updated_at: datetime


class KnowledgeMetadataUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_updated_at: datetime
    reason: str = Field(min_length=1, max_length=500)
    confirm_downgrade: bool = False
    title: str | None = Field(default=None, min_length=1, max_length=500)
    asset_type: AssetType | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    directory_key: str | None = Field(default=None, min_length=1, max_length=100)
    summary: str | None = Field(default=None, min_length=1, max_length=10000)
    confidentiality_level: ConfidentialityLevel | None = None

    @model_validator(mode="after")
    def validate_changes(self):
        fields = self.model_fields_set - {"expected_updated_at", "reason", "confirm_downgrade"}
        if not fields or any(getattr(self, field) is None for field in fields):
            raise ValueError("请提供非空的修改字段")
        if self.expected_updated_at.utcoffset() is None:
            # SQLite-backed deployments return UTC timestamps without an offset.
            self.expected_updated_at = self.expected_updated_at.replace(tzinfo=timezone.utc)
        if self.tags is not None:
            self.tags = list(dict.fromkeys(tag.strip() for tag in self.tags))
            if any(not tag or len(tag) > 100 for tag in self.tags):
                raise ValueError("标签长度应为 1–100 个字符")
        return self

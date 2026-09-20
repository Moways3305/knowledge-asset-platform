import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReleaseEntry(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    kind: Literal["new", "improved", "fixed"]
    text: str = Field(min_length=1, max_length=500)


class ReleaseDraft(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    version: str = Field(pattern=r"^v?\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?$", max_length=40)
    title: str = Field(min_length=1, max_length=120)
    entries: list[ReleaseEntry] = Field(default_factory=list, max_length=50)
    notify_users: bool = True

    @field_validator("version")
    @classmethod
    def canonical_version(cls, value: str) -> str:
        return "v" + value.removeprefix("v")


class ReleaseUpdate(ReleaseDraft):
    revision: int = Field(ge=1)


class PublishRelease(BaseModel):
    revision: int = Field(ge=1)


class ReleaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    version: str
    title: str
    entries: list[ReleaseEntry]
    notify_users: bool
    revision: int
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None
    is_unread: bool = False


class ReleaseList(BaseModel):
    items: list[ReleaseOut]
    total: int
    page: int
    page_size: int


class ReleaseStatus(BaseModel):
    running_version: str
    unread_count: int


class ReadReleases(BaseModel):
    release_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)

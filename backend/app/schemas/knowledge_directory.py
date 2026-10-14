"""Only standard company/project categories can receive a child directory."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.schemas.naming import FormalDirectoryConfig


class DirectoryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["company", "project"]
    project_id: uuid.UUID | None = None
    parent_key: str
    display_name: str

    @field_validator("display_name")
    @classmethod
    def safe_name(cls, value: str) -> str:
        return FormalDirectoryConfig.validate_display_name(value)

    @model_validator(mode="after")
    def project_scope(self):
        if (self.scope == "project") != (self.project_id is not None):
            raise ValueError("项目目录必须指定项目，公司目录不能绑定项目")
        return self


class DirectoryCreateResponse(BaseModel):
    directory_key: str
    name: str

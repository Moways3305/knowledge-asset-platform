"""External LLM connection and business default assignment API schemas."""

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class ModelConnectionOut(BaseModel):
    model_ref: str
    display_name: str
    capability_type: str
    provider: str | None = None
    model_name: str
    enabled: bool
    health_status: str = "untested"
    available_usages: list[str] = Field(default_factory=list)
    legacy_adapter: bool = False


class ModelConnectionListResponse(BaseModel):
    items: list[ModelConnectionOut]
    total: int
    warning: str | None = None


class ModelConnectionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=200)
    capability_type: str
    provider: str = Field(min_length=1, max_length=50)
    model_name: str = Field(min_length=1, max_length=200)
    base_url: SecretStr
    api_key: SecretStr
    enabled: bool = True


class ModelConnectionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=200)
    capability_type: str
    provider: str = Field(min_length=1, max_length=50)
    model_name: str = Field(min_length=1, max_length=200)
    base_url: SecretStr | None = None
    api_key: SecretStr | None = None
    enabled: bool = True


class ModelConnectionTestResponse(BaseModel):
    success: bool
    message: str
    duration_ms: int


class ModelUsageSlotOut(BaseModel):
    model_ref: str | None = None
    display_name: str | None = None
    capability_type: str | None = None


class ModelUsageAssignmentsOut(BaseModel):
    external_llm_default: ModelUsageSlotOut | None = None


class ModelUsageAssignmentsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_llm_default_ref: str | None = None

"""Write-only connection inputs; explicit safe response contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

Capability = Literal["chat", "embedding", "rerank"]
Usage = Literal["business", "knowledge"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EndpointInput(Strict):
    url: SecretStr
    protocol: Literal["openai", "rerank", "dashscope"]


class ConnectionInput(Strict):
    request_id: UUID | None = None
    name: str = Field(min_length=1, max_length=200)
    provider: str = Field(min_length=1, max_length=50)
    api_key: SecretStr | None = None
    region: str = "cn-beijing"
    workspace_id: str = Field(default="", max_length=100)
    endpoints: dict[Capability, EndpointInput] | None = None
    expected_version: int | None = None


class ConnectionOut(BaseModel):
    id: UUID
    name: str
    provider: str
    config_version: int
    credential_version: int
    capabilities: list[str]
    protocols: dict[str, str]
    model_count: int
    affected_models: list[str]


class ModelInput(Strict):
    request_id: UUID
    connection_id: UUID
    display_name: str = Field(min_length=1, max_length=200)
    model_name: str = Field(min_length=1, max_length=200)
    capability: Capability
    dimension: int | None = Field(default=None, ge=1, le=65536)
    usages: list[Usage] = Field(min_length=1, max_length=2)
    expected_version: int | None = None


class VersionInput(Strict):
    signature: str = Field(min_length=1, max_length=100)


class BindingOut(BaseModel):
    status: str
    current: bool
    error_code: str | None = None
    message: str


class RegisteredModelOut(BaseModel):
    id: UUID
    request_id: UUID
    connection_id: UUID
    connection_name: str
    provider: str
    display_name: str
    model_name: str
    capability: str
    dimension: int | None
    usages: list[str]
    version: int
    signature: str
    test_status: str
    test_code: str | None
    test_message: str
    tested_at: datetime | None
    test_duration_ms: int | None
    observed_dimension: int | None
    bindings: dict[str, BindingOut]
    external_ref: str | None
    knowledge_ref: str | None
    busy: bool


class RegistryOut(BaseModel):
    connections: list[ConnectionOut]
    models: list[RegisteredModelOut]

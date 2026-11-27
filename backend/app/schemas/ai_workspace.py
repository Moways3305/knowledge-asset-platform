import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.personal_information import redact_personal_information


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionCreate(Command):
    request_id: uuid.UUID
    agent_key: Literal["knowledge-maintenance"] | None = None
    title: str = Field(default="新会话", min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def clean(cls, value):
        return redact_personal_information(value.strip()) or "新会话"


class SessionPatch(Command):
    title: str = Field(min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def clean(cls, value):
        return redact_personal_information(value.strip()) or "新会话"


class MessageCreate(Command):
    request_id: uuid.UUID
    content: str = Field(min_length=1, max_length=32000)
    model_ref: str = Field(min_length=1, max_length=200)
    context_key: str | None = Field(default=None, max_length=80)

    @field_validator("content")
    @classmethod
    def clean(cls, value):
        value = redact_personal_information(value.strip())
        if not value:
            raise ValueError("请输入任务内容")
        return value


class ResumeCommand(Command):
    request_id: uuid.UUID
    content: str | None = Field(default=None, max_length=32000)

    @field_validator("content")
    @classmethod
    def clean(cls, value):
        return redact_personal_information(value.strip()) or None if value is not None else None


class ActionDecision(Command):
    request_id: uuid.UUID
    decision: Literal["approve", "reject"]


class ArtifactPatch(Command):
    title: str = Field(min_length=1, max_length=120)
    content: str = Field(max_length=160000)
    expected_revision: int = Field(ge=1)

    @field_validator("title", "content")
    @classmethod
    def clean(cls, value):
        return redact_personal_information(value)


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    agent_key: Literal["knowledge-maintenance"] | None = None
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    run_id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime


class PendingAction(BaseModel):
    id: uuid.UUID
    tool: str
    label: str
    summary: str
    arguments: dict


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    status: Literal[
        "queued", "running", "completed", "failed", "stopped", "waiting", "awaiting_confirmation"
    ]
    model_ref: str
    context_key: str | None
    error_code: str | None
    pending_action: PendingAction | None = None
    waiting_reason: str | None = None
    step_count: int = 0
    max_steps: int = 24
    created_at: datetime
    finished_at: datetime | None


class ArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    run_id: uuid.UUID
    title: str
    content: str
    revision: int
    created_at: datetime
    updated_at: datetime


class ActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    run_id: uuid.UUID
    tool: str
    label: str
    status: str
    summary: str
    observation: dict
    created_at: datetime
    updated_at: datetime


class SessionDetail(BaseModel):
    session: SessionOut
    messages: list[MessageOut]
    runs: list[RunOut]
    artifacts: list[ArtifactOut]
    actions: list[ActionOut] = Field(default_factory=list)


class EventOut(BaseModel):
    id: int
    run_id: uuid.UUID
    type: str
    label: str
    created_at: datetime


class EventPage(BaseModel):
    events: list[EventOut]
    cursor: int


class ModelOption(BaseModel):
    model_ref: str
    display_name: str
    is_default: bool


class ContextOption(BaseModel):
    key: str
    label: str


class ToolOption(BaseModel):
    key: str
    label: str
    description: str


class AgentOption(BaseModel):
    key: str
    label: str
    description: str
    tools: list[ToolOption]


class OptionsOut(BaseModel):
    models: list[ModelOption]
    contexts: list[ContextOption]
    tools: list[ToolOption]
    agents: list[AgentOption] = Field(default_factory=list)

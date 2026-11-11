"""Safe selectors shared by administration tools."""

import uuid

from pydantic import BaseModel


class OperationProjectOption(BaseModel):
    id: uuid.UUID
    name: str


class OperationProjectOptions(BaseModel):
    items: list[OperationProjectOption]


class OperationUserOption(BaseModel):
    user_id: uuid.UUID
    name: str
    role_label: str | None = None


class OperationUserOptions(BaseModel):
    items: list[OperationUserOption]

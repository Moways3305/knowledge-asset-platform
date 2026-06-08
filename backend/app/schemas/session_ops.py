"""平台会话运维 API schema。

只承载**安全**会话元数据：安全 `session_id`（非 token hash）、login_method、时间、撤销状态。
**绝不**含 token / token_hash / cookie 值 / OAuth state / ip / device_info / user-agent。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class UserSessionItem(BaseModel):
    session_id: uuid.UUID  # UserSession.id（安全行标识，**非** token hash）
    login_method: str
    created_at: datetime
    last_seen_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None
    active: bool
    is_current_actor_session: bool


class UserSessionsResponse(BaseModel):
    user_id: uuid.UUID
    active_count: int
    sessions: list[UserSessionItem]


class SessionRevokeRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=200)
    # 若目标用户 == 当前 admin 自己，是否保留当前会话（默认撤销全部含自己）。
    preserve_current_session: bool = False


class SessionRevokeResponse(BaseModel):
    ok: bool
    user_id: uuid.UUID
    revoked_count: int
    revoked_at: datetime | None
    preserved_current_session: bool = False


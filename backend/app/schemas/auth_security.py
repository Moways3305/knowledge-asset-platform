"""登录风控运维 API schema。

只承载**安全**字段：不可逆 hash 前缀、计数、安全用户元数据、时间、原因码。**绝不**含
raw email / raw IP / 完整 identifier_hash·ip_hash / password·hash·salt·digest /
session token / token_hash / cookie / OAuth state。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AuthSecurityEventItem(BaseModel):
    """最近一条登录尝试的安全视图（drilldown）。"""

    attempt_id: uuid.UUID
    identifier_hash_prefix: str | None  # hash 前缀，绝非 email
    ip_hash_prefix: str | None  # hash 前缀，绝非原始 IP
    user_id: uuid.UUID | None  # 已知用户才有
    user_name: str | None  # 仅已知用户的安全显示名
    user_status: str | None
    login_method: str
    result: str  # failed / success / locked / rate_limited / unlocked
    reason_code: str | None
    created_at: datetime


class AuthSecurityCounts(BaseModel):
    failed: int = 0
    locked: int = 0
    rate_limited: int = 0
    success: int = 0
    unlocked: int = 0
    unique_identifier_count: int = 0
    unique_ip_count: int = 0


class AuthSecurityOverviewResponse(BaseModel):
    window_minutes: int
    counts: AuthSecurityCounts
    recent_events: list[AuthSecurityEventItem]


class AuthUnlockRequest(BaseModel):
    """手动解锁请求。二选一：user_id（推荐）或 identifier_hash_prefix。

    绝不接受 raw email；identifier_hash_prefix 必须足够长且唯一匹配近期 attempt。"""

    user_id: uuid.UUID | None = None
    identifier_hash_prefix: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=200)


class AuthUnlockResponse(BaseModel):
    ok: bool
    unlocked: bool
    user_id: uuid.UUID | None
    identifier_hash_prefix: str | None
    reset_at: datetime | None

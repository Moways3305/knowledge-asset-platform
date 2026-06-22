"""自助 WorkBuddy 接入 token 的请求 / 响应 schema。

安全：状态视图绝不含 token 明文 / token_hash / header / cookie / provider 内部标识。
明文 token 仅在生成 / 重置成功时一次性返回。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class WorkbuddyTokenStatusOut(BaseModel):
    """当前用户的 WorkBuddy 绑定状态（无 token 明文 / token_hash）。"""

    enabled: bool
    provider: str = "workbuddy"
    bound_user_id: uuid.UUID | None = None
    bound_user_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_rotated_at: datetime | None = None


class WorkbuddyTokenCreatedOut(BaseModel):
    """生成 / 重置结果：明文 token 仅此一次返回，附可直接复制的 mcp.json 配置。"""

    token: str
    mcp_config: dict

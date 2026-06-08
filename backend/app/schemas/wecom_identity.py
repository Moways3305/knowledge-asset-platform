"""企微身份生命周期同步 API schema。

只承载**安全**字段：平台 user_id / 安全显示名 / 平台状态 / 归一 wecom_status code / 计数。
**绝不**含 raw wecom_user_id / access_token / app_secret / OAuth code·state / 上游 payload·errmsg /
手机·邮箱·部门·头像等通讯录档案字段 / session token·hash·cookie。
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class ReconcileRequest(BaseModel):
    """企微身份对账请求（admin-only）。"""

    user_id: uuid.UUID | None = None  # 指定则只对账该绑定用户
    limit: int = Field(default=100, ge=1)
    dry_run: bool = False


class ReconcileItem(BaseModel):
    """单个绑定用户的对账结果（仅安全字段）。"""

    user_id: uuid.UUID
    user_name: str  # 平台显示名（非企微档案）
    previous_status: str
    new_status: str
    wecom_status: str  # 归一 code：active / disabled / not_activated / deleted / unknown
    sessions_revoked: int
    error_code: str | None = None  # 安全 WeComError code（不回显 errmsg）


class ReconcileResponse(BaseModel):
    ok: bool
    checked: int
    deactivated: int
    already_inactive: int
    failed: int
    dry_run: bool
    items: list[ReconcileItem]


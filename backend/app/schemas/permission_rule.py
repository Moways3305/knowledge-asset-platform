"""权限规则配置中心的请求 / 响应 schema。

只暴露**安全治理元数据**：规则 key / 分组 / 类型 / 取值 / 默认值 / 单位 / 说明 /
是否可编辑 / 最后修改人（仅 id + 安全显示名）。**绝不**含任何 secret /
provider 内部标识 / 存储引用 / 业务原文。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class PermissionRuleOut(BaseModel):
    """权限规则安全视图。"""

    rule_id: uuid.UUID
    rule_key: str
    rule_group: str
    rule_type: str
    display_name: str
    value_bool: bool | None = None
    value_number: float | None = None
    value_text: str | None = None
    default_bool: bool | None = None
    default_number: float | None = None
    default_text: str | None = None
    unit: str | None = None
    description: str | None = None
    editable: bool = True
    enabled: bool = True
    updated_by_user_id: uuid.UUID | None = None
    # 安全显示名（无则前端显示 —）；绝不返回邮箱 / 其它身份细节。
    updated_by_name: str | None = None
    updated_at: datetime


class PermissionRulesResponse(BaseModel):
    items: list[PermissionRuleOut]
    total: int


class PermissionRuleUpdateRequest(BaseModel):
    """按 rule_type 更新对应取值；不允许改 rule_key / rule_group / rule_type。

    - numeric 规则：只接受 value_number（建议 >= 0）。
    - toggle 规则：只接受 value_bool。
    - fixed_path 规则：不可修改（服务层拒绝）。
    - 可选 enabled：规则启停（治理元数据）。
    """

    value_bool: bool | None = None
    value_number: float | None = None
    value_text: str | None = None
    enabled: bool | None = None

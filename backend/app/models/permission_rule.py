"""权限规则配置 ORM 模型。

一张表 `permission_rules`（字段命名以前端展示为准）。语义为 **权限治理规则配置中心**：
阈值 / 开关 / 固定路径三类配置项，
由业务治理角色（boss / consulting_director）维护，admin 只读。

边界提醒：
- 本表只存**配置值**，不是 access_grants / original_access_requests。
- **绝不存任何 secret**（token / api_key / provider 内部标识 / 存储引用）。规则值只是
  数字阈值 / 布尔开关 / 安全文本（如验证路径名）。
- `rule_key` 唯一；`rule_type` 决定哪一个 value_* 字段有效。
- `default_*` 保存出厂默认值，供前端展示「默认值」与未来「恢复默认」；`editable=false`
  的固定路径规则只读。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PermissionRule(Base):
    __tablename__ = "permission_rules"
    __table_args__ = (UniqueConstraint("rule_key", name="uq_permission_rules_rule_key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # 规则标识（稳定 key，唯一；不可修改）。
    rule_key: Mapped[str] = mapped_column(String(100), nullable=False)
    # 规则分组（personal_flow / project_upgrade / access_request / asset_lifecycle）。
    rule_group: Mapped[str] = mapped_column(String(50), nullable=False)
    # 规则类型：numeric（数字阈值）/ toggle（开关）/ fixed_path（只读固定路径）。
    rule_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # 安全展示名（中文标签）。
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # 三类取值：按 rule_type 只有其一有效。numeric 用 value_number，toggle 用 value_bool，
    # fixed_path 用 value_text。
    value_bool: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    value_number: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 出厂默认值（前端展示「默认值」/ 未来恢复默认；与 value_* 对应）。
    default_bool: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    default_number: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    default_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 单位（数字阈值的展示单位，如「天」「次」「%」）。
    unit: Mapped[str | None] = mapped_column(String(30), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 是否可编辑（fixed_path 规则为 false，前端只读）。
    editable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 规则是否启用（治理元数据；不影响 fixed_path 的只读语义）。
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 最后修改人（安全显示用；FK → users.id）。
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


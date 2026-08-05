"""会话 ORM 模型。

仅一张表 `user_sessions`，承载服务端会话：浏览器只持有 httpOnly cookie 中的不透明
随机 token，服务端只保存其 sha256 哈希（`token_hash`），**绝不返回明文 token**，也
不把 token 放进任何 JSON 响应（沿用预览凭证只存哈希的口径）。

`login_method` 标识会话来源：`password`（密码登录）、`wecom_oauth`（企业微信 OAuth）、
`dev_local`（开发环境无凭证登录适配器）；不同来源不改变会话机制本身。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.utils import utc_now


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (Index("ix_user_sessions_user", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    # 会话 token 的 sha256 十六进制（64 字符）；明文仅存在于 httpOnly cookie。
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    login_method: Mapped[str] = mapped_column(String(30), nullable=False, default="dev_local")
    # 登录来源 IP（安全溯源元数据，绝不进入 API 响应；守卫路径另有 HMAC 哈希表）。
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 登录设备 UA 截断（同属溯源元数据，不对外）。
    device_info: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

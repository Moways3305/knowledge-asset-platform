"""会话 ORM 模型（IMPLEMENT-12 真实会话身份最小闭环）。

仅一张表 `user_sessions`，承载服务端会话：浏览器只持有 httpOnly cookie 中的不透明
随机 token，服务端只保存其 sha256 哈希（`token_hash`），**绝不返回明文 token**，也
不把 token 放进任何 JSON 响应（沿用 BE-08 预览凭证只存哈希的口径）。

`login_method` 标识会话来源：本阶段为 `dev_local`（本地无凭证登录适配器）；真实
WeCom OAuth 接入后改写此值，不改变会话机制本身。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("ix_user_sessions_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    # 会话 token 的 sha256 十六进制（64 字符）；明文仅存在于 httpOnly cookie。
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    login_method: Mapped[str] = mapped_column(String(30), nullable=False, default="dev_local")
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    device_info: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

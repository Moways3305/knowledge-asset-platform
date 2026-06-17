"""登录失败风控 ORM 模型。

仅一张表 `auth_login_attempts`，承载登录失败守卫所需的**不可逆**安全统计：

- `identifier_hash`：HMAC-SHA256(normalized email)，server-only，不可逆；
- `identifier_hint`：可选短 hint（identifier_hash 前若干位），仅供运营粗略关联，**非 email**；
- `ip_hash`：HMAC-SHA256(client IP)，可空；**绝不**存原始 IP；
- `user_id`：已知用户时填，未知 email 为 null（不泄露账号是否存在）；
- `login_method` / `result` / `reason_code`：安全枚举字符串；
- `trace_id`：链路关联（非鉴权凭证）。

安全红线：本表**绝不**存原始 email / password / hash / salt / digest / session token /
OAuth state / cookie / token_hash / 原始 IP。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.utils import utc_now


class AuthLoginAttempt(Base):
    __tablename__ = "auth_login_attempts"
    __table_args__ = (
        Index("ix_auth_login_attempts_identifier", "identifier_hash", "created_at"),
        Index("ix_auth_login_attempts_ip", "ip_hash", "created_at"),
        Index("ix_auth_login_attempts_user", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # HMAC-SHA256 十六进制（64 字符）；明文 email 绝不入库。
    identifier_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # 安全短 hint（identifier_hash 前缀），仅运营粗略关联用；不存 email/域名。
    identifier_hint: Mapped[str | None] = mapped_column(String(16), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"), nullable=True)
    # HMAC-SHA256(client IP) 十六进制；原始 IP 绝不入库。
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    login_method: Mapped[str] = mapped_column(String(30), nullable=False, default="password")
    # failed / success / locked / rate_limited
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    # invalid_credentials / identifier_locked / ip_rate_limited / success 等安全枚举
    reason_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

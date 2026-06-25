"""平台默认 WeKnora 模型配置（PBC-38）。

单例行：保存平台推荐的 embedding / rerank / chat / multimodal 模型 id。
安全：这些 model_id 是 WeKnora 已注册模型的 server-only 引用，**绝不**进 API 响应 /
审计 extra / 日志 / 前端；对外只暴露不可逆 model_ref（见 weknora_models._model_ref）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.utils import utc_now


class WeknoraDefaultModels(Base):
    __tablename__ = "weknora_default_models"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    default_embedding_model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    default_rerank_model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    default_chat_model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    default_multimodal_model_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

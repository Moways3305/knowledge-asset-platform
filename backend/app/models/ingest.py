"""入库流水线 ORM 模型（IMPLEMENT-05，Path B 最小闭环）。

仅两张表：ingest_tasks / ingest_task_ai_results。本阶段不实现真实文件存储、
真实 AI、Path A 真实扫描、审核流、审计表。

安全：`source_file_ref` 是服务端内部占位引用（不指向真实对象存储/文件），
**禁止进入任何前端响应**。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class IngestTask(Base):
    """入库任务（Path B 本地上传；Path A 暂不真实实现）。"""

    __tablename__ = "ingest_tasks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    # server-only 内部存储引用（指向受控存储），禁止外泄前端。
    source_file_ref: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    source_file_mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 文件内容 sha256（IMPLEMENT-14，去重软提示用；非敏感、可对外做 fingerprint）。
    source_file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    target_scope: Mapped[str | None] = mapped_column(String(20), nullable=True)
    target_project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id"), nullable=True
    )
    target_zone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    result_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("knowledge_assets.id"), nullable=True
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    error_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    ai_result: Mapped[IngestTaskAiResult | None] = relationship(
        back_populates="task", cascade="all, delete-orphan", uselist=False
    )


class IngestTaskAiResult(Base):
    """入库任务的 AI 建议结果（本阶段为基于文件名的确定性占位，不调真实 AI）。"""

    __tablename__ = "ingest_task_ai_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    ingest_task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ingest_tasks.id"), nullable=False
    )
    suggested_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # R2：三层摘要建议。suggested_summary 复用为 detailed；one_liner / key_points 新增。
    suggested_one_liner: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_key_points: Mapped[list | None] = mapped_column(JSON, nullable=True)
    suggested_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # R2：内容处理所用 LLM provider / model（安全运营元数据，非密钥）。
    llm_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    suggested_asset_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    suggested_confidentiality_level: Mapped[str | None] = mapped_column(String(2), nullable=True)
    suggested_ai_access_level: Mapped[str | None] = mapped_column(String(2), nullable=True)
    suggested_phase_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    naming_compliant: Mapped[bool | None] = mapped_column(nullable=True)
    naming_parsed_fields: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    naming_anomalies: Mapped[list | None] = mapped_column(JSON, nullable=True)
    human_corrected: Mapped[bool] = mapped_column(nullable=False, default=False)
    corrected_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    corrected_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 抽取草稿（IMPLEMENT-14）。extracted_text 是业务内容：只在完整视图下可返回，
    # admin 元数据视图不得返回；列表查询应 defer 该列避免放大。
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # extracted / unsupported / failed / empty
    extraction_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 去重软提示（非阻塞）：命中相同内容哈希时指向已有任务 / 资产（均为安全 UUID）。
    duplicate_of_task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    duplicate_of_asset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    task: Mapped[IngestTask] = relationship(back_populates="ai_result")

"""入库流水线 ORM 模型。

仅两张表：ingest_tasks / ingest_task_ai_results（文件存储、AI 抽取、Path A 扫描、
审核流、审计等由各自模块实现）。

安全：`source_file_ref` 是服务端内部存储引用，**禁止进入任何前端响应**。
"""

from __future__ import annotations

import uuid
from datetime import datetime

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
from app.db.utils import utc_now


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
    # 文件内容 sha256。
    source_file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    # Safe workflow marker used by the first-party status API. It never stores provider details.
    processing_stage: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_scope: Mapped[str | None] = mapped_column(String(20), nullable=True)
    target_project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id"), nullable=True
    )
    target_zone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    result_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("knowledge_assets.id"), nullable=True
    )
    # 服务端版本级源文件关联。原文字节读取必须按当前版本匹配，不能仅凭 asset_id
    # 猜测最新入库任务；该字段及其关联的 source_file_ref 均不得进入响应。
    result_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("knowledge_asset_versions.id"), nullable=True, index=True
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    error_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    ai_result: Mapped[IngestTaskAiResult | None] = relationship(
        back_populates="task", cascade="all, delete-orphan", uselist=False
    )


class UploadSession(Base):
    """A caller-owned, recoverable local-upload submission."""

    __tablename__ = "upload_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    total_files: Mapped[int] = mapped_column(Integer, nullable=False)
    total_batches: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    items: Mapped[list[UploadSessionItem]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="UploadSessionItem.ordinal",
    )


class UploadSessionItem(Base):
    """Safe queue metadata; file bytes remain in the task's controlled storage."""

    __tablename__ = "upload_session_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("upload_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ingest_task_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ingest_tasks.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    batch_index: Mapped[int] = mapped_column(Integer, nullable=False)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="waiting")
    safe_error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    safe_error_message: Mapped[str | None] = mapped_column(String(300), nullable=True)
    same_name_warning: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    session: Mapped[UploadSession] = relationship(back_populates="items")


class IngestTaskAiResult(Base):
    """入库任务的 AI 建议结果（外部 LLM 抽取，未配置 LLM 时回退确定性草稿）。"""

    __tablename__ = "ingest_task_ai_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    ingest_task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ingest_tasks.id"), nullable=False
    )
    suggested_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 三层摘要建议。suggested_summary 复用为 detailed；one_liner / key_points 新增。
    suggested_one_liner: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_key_points: Mapped[list | None] = mapped_column(JSON, nullable=True)
    suggested_tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 内容处理所用 LLM provider / model（安全运营元数据，非密钥）。
    llm_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    suggested_asset_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    suggested_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    version_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    version_confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)
    version_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    suggested_confidentiality_level: Mapped[str | None] = mapped_column(String(2), nullable=True)
    confidentiality_source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    confidentiality_confidence: Mapped[str | None] = mapped_column(String(10), nullable=True)
    confidentiality_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
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
    # 抽取草稿。extracted_text 是业务内容：只在完整视图下可返回，
    # admin 元数据视图不得返回；列表查询应 defer 该列避免放大。
    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extracted_char_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # extracted / unsupported / failed / empty
    extraction_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 入库前置规则脱敏安全元数据。仅安全状态与类别计数，**绝不**存脱敏文本或原值。
    # status: applied | unchanged | skipped | failed。counts: 类别 → 替换数量（JSON）。
    desensitization_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    desensitization_counts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    desensitization_error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 去重软提示（非阻塞）：命中相同内容哈希时指向已有任务 / 资产（均为安全 UUID）。
    duplicate_of_task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    duplicate_of_asset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    task: Mapped[IngestTask] = relationship(back_populates="ai_result")

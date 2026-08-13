"""审核域 ORM 模型。

包含：validation_evidences（验证证据）/ review_tasks（审核任务）/
review_task_evidences（任务-证据关联）/ personal_knowledge_submissions（个人知识提交记录）。
`personal_knowledge_submissions` 承载个人知识 → 项目的提交、
内部分享候选与客户验证候选；审核任务支持 material_to_asset 与 personal_to_project。
原文授权（access_grants / original_access_requests）不在本文件。

attachments 仅存占位 metadata（不含真实文件路径/下载 URL）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.utils import utc_now


class ValidationEvidence(Base):
    """验证证据。系统只登记证据，不替代真实业务场景。"""

    __tablename__ = "validation_evidences"
    __table_args__ = (
        Index("ix_validation_evidences_asset_created", "related_asset_id", "created_at"),
        Index(
            "uq_validation_evidence_idempotency",
            "submitted_by",
            "related_asset_id",
            "idempotency_key",
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL"),
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    evidence_type: Mapped[str] = mapped_column(String(30), nullable=False)
    evidence_category: Mapped[str] = mapped_column(String(30), nullable=False)
    related_asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_assets.id"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False)
    submitted_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 占位 metadata 列表，不含真实文件路径/下载 URL。
    attachments: Mapped[list | None] = mapped_column(JSON, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ReviewTask(Base):
    """审核任务。"""

    __tablename__ = "review_tasks"
    __table_args__ = (
        Index("ix_review_tasks_type_status", "review_type", "status"),
        Index("ix_review_tasks_reviewer_status", "reviewer_user_id", "status"),
        UniqueConstraint("source_ingest_task_id", name="uq_review_tasks_source_ingest"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    review_type: Mapped[str] = mapped_column(String(30), nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(50), nullable=False)
    target_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("knowledge_assets.id"), nullable=True
    )
    # 项目上传审批在资产生成前关联 ingest；普通 material_to_asset 任务保持为空。
    source_ingest_task_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("ingest_tasks.id"), nullable=True
    )
    # 人工确认快照仅含请求业务字段，不含文件引用、原文或底座标识。
    confirmation_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    target_project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id"), nullable=True
    )
    target_scope: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    reviewer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    evidence_links: Mapped[list[ReviewTaskEvidence]] = relationship(
        back_populates="review_task", cascade="all, delete-orphan"
    )


class PersonalKnowledgeSubmission(Base):
    """个人知识写动作的提交记录。

    记录"个人知识 → 项目"的提交 / 内部分享候选 / 客户验证候选。系统只登记用户声明的
    提交意图与证据线索，**不**自动证明分享 / 客户验证真实发生；审核仍由项目经理人工确认。

    幂等 / 防重复：
    - `idempotency_key` 非空时，(submitter, source_asset, submission_type, target_project, key)
      唯一（部分唯一索引，PG / SQLite 兼容）。
    - 服务层另对同一 (source_asset, target_project, submission_type) 的 pending 去重，
      避免刷出多个待审任务。
    """

    __tablename__ = "personal_knowledge_submissions"
    __table_args__ = (
        Index(
            "uq_pks_idempotency",
            "submitter_user_id",
            "source_asset_id",
            "submission_type",
            "target_project_id",
            "idempotency_key",
            unique=True,
            sqlite_where=text("idempotency_key IS NOT NULL"),
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index(
            "ix_pks_asset_project_type", "source_asset_id", "target_project_id", "submission_type"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    submitter_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    source_asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_assets.id"), nullable=False
    )
    target_project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id"), nullable=True
    )
    # submit_to_project / internal_sharing_candidate / client_validation_candidate
    submission_type: Mapped[str] = mapped_column(String(40), nullable=False)
    # pending / approved / rejected
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    review_task_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("review_tasks.id"), nullable=True
    )
    evidence_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("validation_evidences.id"), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 用户备注（安全文本；不接收/返回业务原文，写入前经审计同口径脱敏由服务层保证）。
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ReviewTaskEvidence(Base):
    """审核任务与证据的关联（N:N）。"""

    __tablename__ = "review_task_evidences"
    __table_args__ = (UniqueConstraint("review_task_id", "evidence_id", name="uq_review_evidence"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    review_task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("review_tasks.id"), nullable=False
    )
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("validation_evidences.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    review_task: Mapped[ReviewTask] = relationship(back_populates="evidence_links")


class CompanyAssetReviewDecision(Base):
    """项目资产升格公司的追加式双人决定。

    required_role 使用内部稳定键 boss / consulting_director；每次确认、拒绝、撤回均追加新行，
    当前有效状态由各角色最新一行推导，历史决定不会被覆盖。
    """

    __tablename__ = "company_asset_review_decisions"
    __table_args__ = (
        Index(
            "ix_company_asset_review_decisions_task_role_created",
            "review_task_id",
            "required_role",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    review_task_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("review_tasks.id"), nullable=False
    )
    required_role: Mapped[str] = mapped_column(String(40), nullable=False)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

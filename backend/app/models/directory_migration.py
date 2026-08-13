"""Governed, metadata-only migration state for historical active versions."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.utils import utc_now


class DirectoryMigrationCandidate(Base):
    __tablename__ = "directory_migration_candidates"
    __table_args__ = (
        UniqueConstraint("version_id", name="uq_directory_migration_candidate_version"),
        Index("ix_directory_migration_status_scope", "status", "scope"),
        Index("ix_directory_migration_project_status", "project_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_assets.id"), nullable=False
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_asset_versions.id"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id"), nullable=True
    )
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    old_category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    suggested_directory_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    legacy_reference_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    candidate_source: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    rule_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

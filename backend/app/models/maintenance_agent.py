"""Durable, scoped maintenance configuration, scan checkpoints and human decisions."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.utils import utc_now


class MaintenancePolicy(Base):
    __tablename__ = "maintenance_agent_policies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    library_key: Mapped[str] = mapped_column(String(60), unique=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("projects.id"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    content_authorized: Mapped[bool] = mapped_column(Boolean, default=False)
    authorized_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    authorized_role: Mapped[str] = mapped_column(String(30))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    last_scheduled_day: Mapped[str | None] = mapped_column(String(10))
    schedule_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_full_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MaintenanceRun(Base):
    __tablename__ = "maintenance_agent_runs"
    __table_args__ = (Index("ix_maintenance_runs_status_lease", "status", "lease_until"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    policy_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("maintenance_agent_policies.id"))
    policy_revision: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))
    includes_l5: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    target_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("knowledge_assets.id")
    )
    cursor: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    target_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    incomplete_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    reasons: Mapped[dict] = mapped_column(JSON, default=dict)
    claim_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_progress_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MaintenanceCheck(Base):
    __tablename__ = "maintenance_agent_checks"
    __table_args__ = (UniqueConstraint("policy_id", "asset_id", name="uq_maintenance_check_asset"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    policy_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("maintenance_agent_policies.id"))
    asset_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("knowledge_assets.id"))
    fingerprint: Mapped[str] = mapped_column(String(64))
    policy_revision: Mapped[int] = mapped_column(Integer)
    coverage: Mapped[dict] = mapped_column(JSON, default=dict)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MaintenanceIssue(Base):
    __tablename__ = "maintenance_agent_issues"
    __table_args__ = (
        UniqueConstraint(
            "policy_id", "asset_id", "rule", "related_key", name="uq_maintenance_issue_fact"
        ),
        Index("ix_maintenance_issue_policy_status", "policy_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    policy_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("maintenance_agent_policies.id"))
    asset_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("knowledge_assets.id"))
    version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    rule: Mapped[str] = mapped_column(String(60))
    category: Mapped[str] = mapped_column(String(30))
    related_key: Mapped[str] = mapped_column(String(36), default="")
    related_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("knowledge_assets.id")
    )
    fingerprint: Mapped[str] = mapped_column(String(64))
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    suspected: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(24), default="open")
    snooze_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MaintenanceIssueEvent(Base):
    __tablename__ = "maintenance_agent_issue_events"
    __table_args__ = (Index("ix_maintenance_events_issue", "issue_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    issue_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("maintenance_agent_issues.id"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MaintenanceDigest(Base):
    __tablename__ = "maintenance_agent_digests"
    __table_args__ = (
        UniqueConstraint("recipient_id", "day", name="uq_maintenance_digest_recipient_day"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    recipient_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    day: Mapped[str] = mapped_column(String(10))
    issue_ids: Mapped[list] = mapped_column(JSON, default=list)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

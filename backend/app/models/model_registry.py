"""Versioned provider connections and resumable model onboarding. Secrets never leave server."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.utils import utc_now


class ProviderConnection(Base):
    __tablename__ = "provider_connections"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    provider: Mapped[str] = mapped_column(String(50))
    config_ciphertext: Mapped[str] = mapped_column(Text)
    key_ciphertext: Mapped[str] = mapped_column(Text)
    config_version: Mapped[int] = mapped_column(Integer, default=1)
    credential_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RegisteredModel(Base):
    __tablename__ = "registered_models"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("provider_connections.id"))
    display_name: Mapped[str] = mapped_column(String(200))
    model_name: Mapped[str] = mapped_column(String(200))
    capability: Mapped[str] = mapped_column(String(20))
    dimension: Mapped[int | None] = mapped_column(Integer)
    usages: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    tested_signature: Mapped[str | None] = mapped_column(String(100))
    test_status: Mapped[str] = mapped_column(String(30), default="untested")
    test_code: Mapped[str | None] = mapped_column(String(60))
    tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    test_duration_ms: Mapped[int | None] = mapped_column(Integer)
    observed_dimension: Mapped[int | None] = mapped_column(Integer)
    bindings: Mapped[dict] = mapped_column(JSON, default=dict)
    external_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("content_generation_models.id")
    )
    weknora_id: Mapped[str | None] = mapped_column(String(200))
    creation_uncertain: Mapped[str | None] = mapped_column(String(100))
    operation_token: Mapped[str | None] = mapped_column(String(40))
    operation_started: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

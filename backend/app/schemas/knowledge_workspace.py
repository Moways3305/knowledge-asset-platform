"""Typed, redacted source evidence for workspace knowledge tools."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class SourceLink(BaseModel):
    asset_id: uuid.UUID
    title: str


class KnowledgeEvidence(BaseModel):
    asset_id: uuid.UUID
    version_id: uuid.UUID
    title: str
    version: str
    summary: str | None
    original: bool
    matched: list[str]
    summary_matched: list[str]
    unmatched: list[str]
    old_source_links: list[SourceLink]
    needs_update: bool
    pending_update: bool
    parsed: bool
    correction_status: str | None
    history_truncated: bool
    compared_version: str | None
    changed_fields: list[str]
    previous_summary: str | None
    current_summary: str | None
    updated_at: datetime

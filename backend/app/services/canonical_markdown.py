"""Canonical Markdown generation and controlled server-side retrieval.

Original bytes remain the audit source. This module creates one deterministic
Markdown derivative per ingest task and makes that derivative the only payload
accepted by the WeKnora indexing boundary.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.utils import utc_now
from app.models.ingest import IngestTask, IngestTaskDerivative
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetFileObject, KnowledgeAssetVersion
from app.services.extraction import extract_text
from app.services.source_content import resolve_version_source_task
from app.services.storage import LocalFileStorage, StorageError

FORMAT_VERSION = "kap-md-v1"
DERIVATIVE_TYPE = "canonical_markdown"
FILE_VARIANT = "canonical_markdown"
MARKDOWN_MIME = "text/markdown"


class CanonicalMarkdownUnavailable(Exception):
    """Safe failure used by retry, reparse, migration, and backfill callers."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CanonicalMarkdownPayload:
    content: bytes
    file_name: str
    mime: str
    text: str
    content_hash: str
    task: IngestTask
    derivative: IngestTaskDerivative


def task_markdown_is_valid(
    storage: LocalFileStorage, derivative: IngestTaskDerivative | None
) -> bool:
    """Validate controlled bytes before a task can enter confirmation/review."""
    if (
        derivative is None
        or derivative.status != "ready"
        or not derivative.storage_ref
        or not derivative.content_hash
    ):
        return False
    try:
        content = storage.resolve_path(derivative.storage_ref).read_bytes()
        text = content.decode("utf-8")
    except (OSError, StorageError, UnicodeDecodeError, ValueError):
        return False
    return bool(text.strip()) and hashlib.sha256(content).hexdigest() == derivative.content_hash


def _display_source_name(value: str) -> str:
    value = os.path.basename((value or "source").replace("\\", "/"))
    value = " ".join(value.replace("\r", " ").replace("\n", " ").split())
    return (value or "source")[:240]


def canonical_file_name(source_file_name: str) -> str:
    source = _display_source_name(source_file_name)
    stem, _suffix = os.path.splitext(source)
    return f"{(stem or 'knowledge')[:220]}.canonical.md"


def render_canonical_markdown(*, extracted_text: str, source_file_name: str) -> bytes:
    """Render stable UTF-8 Markdown using source facts only, never AI suggestions."""
    source = _display_source_name(source_file_name)
    stem, _suffix = os.path.splitext(source)
    title = (stem or "知识正文").replace("#", "").strip() or "知识正文"
    body = extracted_text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not body:
        raise CanonicalMarkdownUnavailable("canonical_markdown_empty")
    markdown = (
        f"# {title}\n\n> 来源文件：{source}（来源事实，非人工确认元数据）\n\n## 正文\n\n{body}\n"
    )
    return markdown.encode("utf-8")


async def ensure_task_markdown(
    session: AsyncSession,
    storage: LocalFileStorage,
    *,
    task: IngestTask,
    extracted_text: str,
) -> IngestTaskDerivative:
    """Create or reuse the task derivative without producing unrelated copies."""
    content = render_canonical_markdown(
        extracted_text=extracted_text,
        source_file_name=task.source_file_name,
    )
    content_hash = hashlib.sha256(content).hexdigest()
    source_hash = task.source_file_hash
    derivative = (
        await session.execute(
            select(IngestTaskDerivative).where(
                IngestTaskDerivative.ingest_task_id == task.id,
                IngestTaskDerivative.derivative_type == DERIVATIVE_TYPE,
            )
        )
    ).scalar_one_or_none()
    if (
        derivative is not None
        and derivative.status == "ready"
        and derivative.format_version == FORMAT_VERSION
        and derivative.source_content_hash == source_hash
        and derivative.content_hash == content_hash
        and derivative.storage_ref
        and storage.exists(derivative.storage_ref)
    ):
        return derivative

    storage_ref = storage.save(content, original_name=canonical_file_name(task.source_file_name))
    if derivative is None:
        derivative = IngestTaskDerivative(
            ingest_task_id=task.id,
            derivative_type=DERIVATIVE_TYPE,
        )
        session.add(derivative)
    derivative.status = "ready"
    derivative.format_version = FORMAT_VERSION
    derivative.source_content_hash = source_hash
    derivative.content_hash = content_hash
    derivative.storage_ref = storage_ref
    derivative.generated_at = utc_now()
    derivative.failure_code = None
    await session.flush()
    return derivative


async def mark_task_markdown_failed(
    session: AsyncSession, task: IngestTask, *, code: str
) -> IngestTaskDerivative:
    derivative = (
        await session.execute(
            select(IngestTaskDerivative).where(
                IngestTaskDerivative.ingest_task_id == task.id,
                IngestTaskDerivative.derivative_type == DERIVATIVE_TYPE,
            )
        )
    ).scalar_one_or_none()
    if derivative is None:
        derivative = IngestTaskDerivative(
            ingest_task_id=task.id,
            derivative_type=DERIVATIVE_TYPE,
        )
        session.add(derivative)
    derivative.status = "failed"
    derivative.failure_code = code
    derivative.generated_at = None
    await session.flush()
    return derivative


async def _file_object(
    session: AsyncSession, *, asset_id: uuid.UUID, version_id: uuid.UUID
) -> KnowledgeAssetFileObject | None:
    return (
        await session.execute(
            select(KnowledgeAssetFileObject).where(
                KnowledgeAssetFileObject.asset_id == asset_id,
                KnowledgeAssetFileObject.version_id == version_id,
                KnowledgeAssetFileObject.file_variant == FILE_VARIANT,
            )
        )
    ).scalar_one_or_none()


async def ensure_version_markdown(
    session: AsyncSession,
    storage: LocalFileStorage,
    *,
    asset_id: uuid.UUID,
    version_id: uuid.UUID,
) -> CanonicalMarkdownPayload:
    """Load saved Markdown, or backfill it once from a still-available original."""
    task = await resolve_version_source_task(session, asset_id=asset_id, version_id=version_id)
    if task is None:
        raise CanonicalMarkdownUnavailable("canonical_markdown_source_missing")

    file_object = await _file_object(session, asset_id=asset_id, version_id=version_id)
    derivative = (
        await session.execute(
            select(IngestTaskDerivative).where(
                IngestTaskDerivative.ingest_task_id == task.id,
                IngestTaskDerivative.derivative_type == DERIVATIVE_TYPE,
            )
        )
    ).scalar_one_or_none()

    storage_ref = file_object.storage_ref if file_object is not None else None
    expected_hash = file_object.file_hash if file_object is not None else None
    if not storage_ref and derivative is not None:
        storage_ref = derivative.storage_ref
        expected_hash = derivative.content_hash
    if storage_ref:
        try:
            content = storage.resolve_path(storage_ref).read_bytes()
        except (OSError, StorageError, ValueError):
            content = b""
        actual_hash = hashlib.sha256(content).hexdigest() if content else None
        if content and actual_hash == expected_hash:
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                text = ""
            if text:
                if derivative is None:
                    derivative = IngestTaskDerivative(
                        ingest_task_id=task.id,
                        derivative_type=DERIVATIVE_TYPE,
                    )
                    session.add(derivative)
                derivative.status = "ready"
                derivative.format_version = FORMAT_VERSION
                derivative.source_content_hash = task.source_file_hash
                derivative.content_hash = actual_hash
                derivative.storage_ref = storage_ref
                derivative.generated_at = derivative.generated_at or utc_now()
                derivative.failure_code = None
                derivative.linked_version_id = version_id
                await session.flush()
                return CanonicalMarkdownPayload(
                    content=content,
                    file_name=canonical_file_name(task.source_file_name),
                    mime=MARKDOWN_MIME,
                    text=text,
                    content_hash=actual_hash or "",
                    task=task,
                    derivative=derivative,
                )

    # Historical compatibility: regenerate only when the saved derivative is
    # missing or invalid, then persist it before any WeKnora call.
    try:
        original = storage.resolve_path(task.source_file_ref).read_bytes()
    except (OSError, StorageError, ValueError) as exc:
        await mark_task_markdown_failed(session, task, code="canonical_markdown_source_missing")
        raise CanonicalMarkdownUnavailable("canonical_markdown_source_missing") from exc
    extraction = extract_text(
        original,
        file_name=task.source_file_name,
        mime=task.source_file_mime_type,
    )
    if extraction.status != "extracted" or not extraction.text:
        code = "canonical_markdown_extraction_failed"
        await mark_task_markdown_failed(session, task, code=code)
        raise CanonicalMarkdownUnavailable(code)
    derivative = await ensure_task_markdown(
        session,
        storage,
        task=task,
        extracted_text=extraction.text,
    )
    derivative.linked_version_id = version_id
    content = storage.resolve_path(derivative.storage_ref or "").read_bytes()
    if file_object is None:
        asset = await session.get(KnowledgeAsset, asset_id)
        version = await session.get(KnowledgeAssetVersion, version_id)
        if asset is None or version is None:
            raise CanonicalMarkdownUnavailable("canonical_markdown_version_missing")
        file_object = KnowledgeAssetFileObject(
            asset_id=asset_id,
            version_id=version_id,
            file_variant=FILE_VARIANT,
            file_name=canonical_file_name(task.source_file_name),
            file_mime_type=MARKDOWN_MIME,
            file_size=len(content),
            storage_ref=derivative.storage_ref or "",
            file_hash=derivative.content_hash,
            confidentiality_level=asset.confidentiality_level,
        )
        session.add(file_object)
    else:
        file_object.file_name = canonical_file_name(task.source_file_name)
        file_object.file_mime_type = MARKDOWN_MIME
        file_object.file_size = len(content)
        file_object.storage_ref = derivative.storage_ref or ""
        file_object.file_hash = derivative.content_hash
    await session.flush()
    return CanonicalMarkdownPayload(
        content=content,
        file_name=file_object.file_name,
        mime=MARKDOWN_MIME,
        text=content.decode("utf-8"),
        content_hash=derivative.content_hash or "",
        task=task,
        derivative=derivative,
    )

from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.worker.queues import ingest_processing_queue


@pytest.mark.parametrize(
    "file_name,mime_type",
    [
        ("notes.txt", "text/plain"),
        ("notes.md", "application/octet-stream"),
        ("legacy-name", "text/csv"),
    ],
)
def test_plain_text_ingest_uses_default_queue(file_name, mime_type):
    settings = get_settings()
    assert (
        ingest_processing_queue(settings, file_name=file_name, mime_type=mime_type)
        == settings.celery_default_queue
    )


@pytest.mark.parametrize(
    "file_name,mime_type",
    [
        ("report.pdf", "application/pdf"),
        ("slides.pptx", "application/octet-stream"),
        ("book.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("photo.webp", "image/webp"),
        ("document.txt", "application/pdf"),
        ("unknown.bin", "application/octet-stream"),
    ],
)
def test_structured_or_unknown_ingest_uses_heavy_queue(file_name, mime_type):
    settings = get_settings()
    assert (
        ingest_processing_queue(settings, file_name=file_name, mime_type=mime_type)
        == settings.celery_ocr_queue
    )


@pytest.mark.parametrize(
    "stage",
    [
        "canonical_markdown_generation",
        "content_generation_queued",
        "content_generation",
        "content_generation_failed",
        "waiting_generation_config",
    ],
)
def test_content_generation_continuation_uses_default_queue(stage):
    settings = get_settings()
    assert (
        ingest_processing_queue(
            settings,
            file_name="large-file.pdf",
            mime_type="application/pdf",
            processing_stage=stage,
        )
        == settings.celery_default_queue
    )

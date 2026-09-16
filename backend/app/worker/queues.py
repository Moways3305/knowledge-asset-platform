"""Queue selection for upload processing tasks.

Keep supported structured formats on the resource-isolated worker. Only source
formats that the extractor reads as bounded plain text and content-generation
continuations use the ordinary queue. Unknown/binary formats fail closed to the
heavy queue rather than unexpectedly occupying a light-task worker.
"""

from __future__ import annotations

from app.core.config import Settings

_CONTENT_ONLY_STAGES = frozenset(
    {
        "canonical_markdown_generation",
        "content_generation_queued",
        "content_generation",
        "content_generation_failed",
        "waiting_generation_config",
    }
)
_TEXT_EXTENSIONS = frozenset({"txt", "md", "markdown", "csv", "log", "text", "rst"})
_PARSER_FORMAT_EXTENSIONS = frozenset(
    {
        *_TEXT_EXTENSIONS,
        "pdf",
        "doc",
        "docx",
        "ppt",
        "pptx",
        "xls",
        "xlsx",
        "png",
        "jpg",
        "jpeg",
        "tif",
        "tiff",
        "bmp",
        "webp",
    }
)
_OFFICE_MIME_TYPES = frozenset(
    {
        "application/msword",
        "application/vnd.ms-powerpoint",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)


def ingest_processing_queue(
    settings: Settings,
    *,
    file_name: str | None,
    mime_type: str | None,
    processing_stage: str | None = None,
) -> str:
    """Return the queue for initial dispatch and recovery of one ingest task."""
    if is_content_generation_stage(processing_stage):
        return settings.celery_default_queue

    mime = (mime_type or "").strip().lower()
    name = (file_name or "").strip().lower()
    extension = name.rsplit(".", 1)[-1] if "." in name else ""

    if (
        mime == "application/pdf"
        or mime.startswith("image/")
        or mime in _OFFICE_MIME_TYPES
        or extension in _PARSER_FORMAT_EXTENSIONS - _TEXT_EXTENSIONS
    ):
        return settings.celery_ocr_queue

    # Extraction treats an unknown extension with text/* MIME as plain text.
    # Known structured extensions remain heavy even if their supplied MIME lies.
    if extension in _TEXT_EXTENSIONS or (
        extension not in _PARSER_FORMAT_EXTENSIONS and mime.startswith("text/")
    ):
        return settings.celery_default_queue

    # An unknown or binary format is safer to classify as heavy: it may turn out
    # to be a renamed PDF/image/office file and must not pin the light worker.
    return settings.celery_ocr_queue


def is_content_generation_stage(processing_stage: str | None) -> bool:
    return processing_stage in _CONTENT_ONLY_STAGES


def is_ocr_candidate(*, file_name: str | None, mime_type: str | None) -> bool:
    mime = (mime_type or "").strip().lower()
    name = (file_name or "").strip().lower()
    extension = name.rsplit(".", 1)[-1] if "." in name else ""
    return (
        mime == "application/pdf"
        or mime.startswith("image/")
        or extension in {"pdf", "png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"}
    )

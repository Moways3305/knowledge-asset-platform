"""Bounded local OCR; rendering and Tesseract run in killable subprocesses."""

from __future__ import annotations

import io
import subprocess
import sys
import time
from dataclasses import dataclass

from PIL import Image

from app.core.config import get_settings
from app.core.text_safety import EXTRACTED_TEXT_MAX_CHARS, SafetyStats, sanitize_text
from app.services.extraction import MAX_EXTRACT_CHARS, ExtractionPage, ExtractionResult


class OCRError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class OCRPageResult:
    page_number: int
    text: str
    status: str
    confidence: float | None
    rendered_pixels: int = 0


@dataclass(frozen=True)
class OCRResult:
    text: str
    status: str
    confidence: float | None
    pages: tuple[OCRPageResult, ...]
    error_type: str | None = None
    error_message: str | None = None
    safety_stats: SafetyStats = SafetyStats()


def validate_document(content: bytes, extraction: ExtractionResult) -> None:
    settings = get_settings()
    pages = extraction.pages or (ExtractionPage(1, "", "ocr_required"),)
    if len(content) > settings.ocr_max_image_bytes or len(pages) > settings.ocr_max_pages:
        raise OCRError(
            "ocr_resource_limit",
            "文件过大或过于复杂，请拆分文件或转为人工处理。",
            retryable=False,
        )


def _image_bytes(content: bytes, *, source_kind: str, page_number: int) -> bytes:
    settings = get_settings()
    # Image uploads are already bounded by upload bytes; validate dimensions before conversion.
    # PDF rasterization remains isolated because it is the incident's dominant unbounded path.
    if source_kind == "image":
        try:
            with Image.open(io.BytesIO(content)) as source:
                if source.width * source.height > settings.ocr_max_rendered_pixels:
                    raise OCRError(
                        "ocr_resource_limit",
                        "文件过大或过于复杂，请拆分文件或转为人工处理。",
                        retryable=False,
                    )
                image = source.convert("RGB")
                out = io.BytesIO()
                image.save(out, format="PNG")
                return out.getvalue()
        except OCRError:
            raise
        except Exception as exc:
            raise OCRError(
                "ocr_source_invalid", "图片无法读取，请检查文件是否损坏。", retryable=False
            ) from exc
    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "app.services.ocr_render_worker",
                source_kind,
                str(page_number),
                str(settings.ocr_max_rendered_pixels),
            ],
            input=content,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=max(1, settings.ocr_render_timeout_seconds),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OCRError(
            "ocr_render_timeout", "PDF 页面渲染超时，系统将有限重试。", retryable=True
        ) from exc
    if completed.returncode == 3:
        raise OCRError(
            "ocr_resource_limit",
            "文件过大或过于复杂，请拆分文件或转为人工处理。",
            retryable=False,
        )
    if completed.returncode != 0 or not completed.stdout:
        raise OCRError("ocr_source_invalid", "PDF 无法读取，请检查文件是否损坏。", retryable=False)
    try:
        with Image.open(io.BytesIO(completed.stdout)) as image:
            if image.width * image.height > settings.ocr_max_rendered_pixels:
                raise OCRError(
                    "ocr_resource_limit",
                    "文件过大或过于复杂，请拆分文件或转为人工处理。",
                    retryable=False,
                )
    except OCRError:
        raise
    except Exception as exc:
        raise OCRError(
            "ocr_source_invalid", "PDF 无法读取，请检查文件是否损坏。", retryable=False
        ) from exc
    return completed.stdout


def _recognize_page(image: bytes) -> tuple[str, float | None]:
    settings = get_settings()
    try:
        completed = subprocess.run(
            [settings.ocr_command, "stdin", "stdout", "-l", settings.ocr_languages, "tsv"],
            input=image,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=max(1, settings.ocr_page_timeout_seconds),
            check=False,
        )
    except FileNotFoundError as exc:
        raise OCRError(
            "ocr_not_configured", "OCR 服务暂不可用，原文已保留。", retryable=True
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise OCRError(
            "ocr_page_timeout", "单页 OCR 超时，系统将有限重试。", retryable=True
        ) from exc
    if completed.returncode != 0:
        raise OCRError("ocr_process_failed", "OCR 子进程异常退出，系统将有限重试。", retryable=True)
    words: list[str] = []
    confidence: list[float] = []
    for line in completed.stdout.decode("utf-8", errors="replace").splitlines()[1:]:
        columns = line.split("\t")
        if len(columns) < 12 or not columns[11].strip():
            continue
        words.append(columns[11].strip())
        try:
            value = float(columns[10])
            if value >= 0:
                confidence.append(value)
        except ValueError:
            pass
    return " ".join(words).strip(), sum(confidence) / len(confidence) if confidence else None


def recognize_page(
    content: bytes, extraction: ExtractionResult, page: ExtractionPage
) -> OCRPageResult:
    settings = get_settings()
    if page.status == "extracted":
        return OCRPageResult(page.page_number, page.text, "skipped_text", None)
    image_bytes = _image_bytes(
        content, source_kind=extraction.source_kind, page_number=page.page_number
    )
    with Image.open(io.BytesIO(image_bytes)) as image:
        rendered_pixels = image.width * image.height
    text, confidence = _recognize_page(image_bytes)
    status = (
        "succeeded"
        if text and confidence is not None and confidence >= settings.ocr_min_confidence
        else "low_confidence"
    )
    return OCRPageResult(page.page_number, text, status, confidence, rendered_pixels)


def build_result(pages: list[OCRPageResult]) -> OCRResult:
    merged = [f"{{{{page:{page.page_number}}}}}\n{page.text}" for page in pages if page.text]
    confidences = [page.confidence for page in pages if page.confidence is not None]
    overall = sum(confidences) / len(confidences) if confidences else None
    status = (
        "succeeded"
        if all(page.status in {"succeeded", "skipped_text"} for page in pages)
        else "low_confidence"
    )
    safe_text = sanitize_text("\n".join(merged), max_chars=EXTRACTED_TEXT_MAX_CHARS)
    return OCRResult(
        text=safe_text.value[:MAX_EXTRACT_CHARS],
        status=status,
        confidence=overall,
        pages=tuple(pages),
        error_type=None if status == "succeeded" else "ocr_low_confidence",
        error_message=None if status == "succeeded" else "OCR 置信度不足，请检查原文或重试。",
        safety_stats=safe_text.stats,
    )


def recognize(
    content: bytes,
    extraction: ExtractionResult,
    *,
    completed_pages: dict[int, OCRPageResult] | None = None,
) -> OCRResult:
    settings = get_settings()
    if not settings.ocr_enabled:
        raise OCRError("ocr_disabled", "OCR 已禁用，原文已保留。")
    validate_document(content, extraction)
    started = time.monotonic()
    results: list[OCRPageResult] = []
    total_pixels = 0
    required = extraction.pages or (ExtractionPage(1, "", "ocr_required"),)
    for page in required:
        saved = (completed_pages or {}).get(page.page_number)
        if saved and saved.status in {"succeeded", "skipped_text"}:
            result = saved
        else:
            if time.monotonic() - started > settings.ocr_document_timeout_seconds:
                raise OCRError(
                    "ocr_document_timeout", "整份文件 OCR 超时，系统将有限重试。", retryable=True
                )
            result = recognize_page(content, extraction, page)
        total_pixels += result.rendered_pixels
        if total_pixels > settings.ocr_max_total_pixels:
            raise OCRError(
                "ocr_resource_limit",
                "文件过大或过于复杂，请拆分文件或转为人工处理。",
                retryable=False,
            )
        results.append(result)
    return build_result(results)

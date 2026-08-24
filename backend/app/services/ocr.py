"""Local-only OCR for ingest recovery; original bytes never leave the process boundary."""

from __future__ import annotations

import io
import subprocess
from dataclasses import dataclass

from app.core.config import get_settings
from app.services.extraction import MAX_EXTRACT_CHARS, ExtractionPage, ExtractionResult


class OCRError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class OCRPageResult:
    page_number: int
    text: str
    status: str
    confidence: float | None


@dataclass(frozen=True)
class OCRResult:
    text: str
    status: str  # succeeded | low_confidence | failed
    confidence: float | None
    pages: tuple[OCRPageResult, ...]
    error_type: str | None = None
    error_message: str | None = None


def _image_bytes(content: bytes, *, source_kind: str, page_number: int) -> bytes:
    try:
        if source_kind == "image":
            from PIL import Image

            image = Image.open(io.BytesIO(content)).convert("RGB")
            out = io.BytesIO()
            image.save(out, format="PNG")
            return out.getvalue()
        import fitz

        document = fitz.open(stream=content, filetype="pdf")
        try:
            page = document.load_page(page_number - 1)
            return page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).tobytes("png")
        finally:
            document.close()
    except OCRError:
        raise
    except Exception as exc:
        raise OCRError("ocr_source_invalid", "原文无法读取，OCR 未执行。") from exc


def _recognize_page(image: bytes) -> tuple[str, float | None]:
    settings = get_settings()
    try:
        completed = subprocess.run(
            [settings.ocr_command, "stdin", "stdout", "-l", settings.ocr_languages, "tsv"],
            input=image,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=60,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        code = "ocr_not_configured" if isinstance(exc, FileNotFoundError) else "ocr_timeout"
        raise OCRError(code, "OCR 服务暂不可用。") from exc
    if completed.returncode != 0:
        raise OCRError("ocr_failed", "OCR 识别未完成。")
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


def recognize(content: bytes, extraction: ExtractionResult) -> OCRResult:
    settings = get_settings()
    if not settings.ocr_enabled:
        raise OCRError("ocr_disabled", "OCR 已禁用，原文已保留。")
    pages: list[OCRPageResult] = []
    merged: list[str] = []
    required = extraction.pages or (ExtractionPage(1, "", "ocr_required"),)
    for page in required:
        if page.status == "extracted":
            result = OCRPageResult(page.page_number, page.text, "skipped_text", None)
        else:
            text, confidence = _recognize_page(
                _image_bytes(
                    content, source_kind=extraction.source_kind, page_number=page.page_number
                )
            )
            status = (
                "succeeded"
                if text and confidence is not None and confidence >= settings.ocr_min_confidence
                else "low_confidence"
            )
            result = OCRPageResult(page.page_number, text, status, confidence)
        pages.append(result)
        if result.text:
            merged.append(f"{{{{page:{result.page_number}}}}}\n{result.text}")
    confidences = [p.confidence for p in pages if p.confidence is not None]
    overall = sum(confidences) / len(confidences) if confidences else None
    status = (
        "succeeded"
        if all(p.status in {"succeeded", "skipped_text"} for p in pages)
        else "low_confidence"
    )
    return OCRResult(
        text="\n".join(merged)[:MAX_EXTRACT_CHARS],
        status=status,
        confidence=overall,
        pages=tuple(pages),
        error_type=None if status == "succeeded" else "ocr_low_confidence",
        error_message=None if status == "succeeded" else "OCR 置信度不足，请检查原文或重试。",
    )

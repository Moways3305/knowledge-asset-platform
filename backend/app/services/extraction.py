"""文本抽取服务（IMPLEMENT-14 入库抽取管线最小闭环）。

输入文件字节 + 文件名 / mime，输出抽取全文草稿 + 状态。纯 Python 抽取库
（txt/md 直读、pdf 用 pypdf、docx 用 python-docx），Windows 无原生二进制依赖。

边界（本任务不做，见任务说明）：不接真实 LLM / 大模型；不做 OCR；不支持
xlsx / pptx / 图片（标 `unsupported`，不崩溃、不阻断任务创建）；不做切块 / 向量化。

安全：抽取全文是**用户业务内容**，可能含 `s3://` / `internal://` / URL 等字样——
它只准进草稿 / 资产侧，**绝不准进审计 extra/after**（审计只放安全元数据）。
"""

from __future__ import annotations

import io
from dataclasses import dataclass

# 抽取草稿全文上限（防超大文本放大）；超过则截断。
MAX_EXTRACT_CHARS = 200_000

# 直接按文本读取的扩展名。
_TEXT_EXT = {"txt", "md", "markdown", "csv", "log", "text", "rst"}

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@dataclass(frozen=True)
class ExtractionResult:
    """抽取结果。status ∈ extracted / unsupported / failed / empty。"""

    text: str
    status: str
    error_type: str | None
    error_message: str | None
    char_count: int


def _ext(file_name: str | None) -> str:
    name = file_name or ""
    return name.rsplit(".", 1)[1].lower() if "." in name else ""


def _extract_pdf(content: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    parts: list[str] = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _extract_docx(content: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(content))
    return "\n".join(p.text for p in doc.paragraphs)


def extract_text(
    content: bytes, *, file_name: str | None, mime: str | None
) -> ExtractionResult:
    """按扩展名 / mime 路由抽取文本，返回结构化结果（绝不抛出到调用方）。"""
    ext = _ext(file_name)
    mime = (mime or "").lower()
    try:
        if ext in _TEXT_EXT or mime.startswith("text/"):
            # 非 UTF-8 稳健回退：用 replace，不因解码异常把任务打成 failed。
            text = content.decode("utf-8", errors="replace")
        elif ext == "pdf" or mime == "application/pdf":
            text = _extract_pdf(content)
        elif ext == "docx" or mime == _DOCX_MIME:
            text = _extract_docx(content)
        else:
            return ExtractionResult(
                text="",
                status="unsupported",
                error_type="extraction_unsupported",
                error_message=(
                    f"暂不支持从 .{ext or '该类型'} 文件抽取文本（文件已落盘，请人工补全内容）"
                ),
                char_count=0,
            )
    except Exception:  # noqa: BLE001 — 损坏 / 格式不符文件：降级为 failed，不崩溃
        return ExtractionResult(
            text="",
            status="failed",
            error_type="extraction_failed",
            error_message="文件内容无法解析（可能已损坏或与扩展名不符），请重新上传或人工补全",
            char_count=0,
        )

    text = text.strip()
    if not text:
        # 纯图片 / 扫描件 PDF 等抽不到文本。
        return ExtractionResult(
            text="",
            status="empty",
            error_type="extraction_empty",
            error_message="未能从文件内容中抽取到文本（可能是扫描件 / 纯图片），请人工补全",
            char_count=0,
        )
    if len(text) > MAX_EXTRACT_CHARS:
        text = text[:MAX_EXTRACT_CHARS]
    return ExtractionResult(
        text=text, status="extracted", error_type=None, error_message=None,
        char_count=len(text),
    )

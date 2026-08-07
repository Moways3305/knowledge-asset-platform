"""文本抽取服务。

输入文件字节 + 文件名 / mime，输出抽取全文草稿 + 状态。纯 Python 抽取库
（txt/md 直读、pdf 用 pypdf、docx 用 python-docx、pptx 用 python-pptx、
xlsx 用 openpyxl 转 markdown 表格），Windows 无原生二进制依赖。

边界：不接真实 LLM / 大模型；不做 OCR；不支持 旧版 .xls / 图片
（标 `unsupported`，不崩溃、不阻断任务创建）；不做切块 / 向量化。

安全：抽取全文是**用户业务内容**，可能含 `s3://` / `internal://` / URL 等字样——
它只准进草稿 / 资产侧，**绝不准进审计 extra/after**（审计只放安全元数据）。
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

from app.core.logging import safe_log_exception

_logger = logging.getLogger(__name__)

# 抽取草稿全文上限（防超大文本放大）；超过则截断。
MAX_EXTRACT_CHARS = 200_000

# 直接按文本读取的扩展名。
_TEXT_EXT = {"txt", "md", "markdown", "csv", "log", "text", "rst"}

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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
    for index, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        # 页码标记（D1 阶段3）：供 chunk 注册表记录 source_page / 查看原文定位。
        parts.append(f"{{{{page:{index}}}}}\n{page_text}" if page_text else "")
    return "\n".join(parts)


def _extract_docx(content: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(content))
    return "\n".join(p.text for p in doc.paragraphs)


def _pptx_shape_text(shape) -> list[str]:
    """Extract readable text from one shape while preserving its child order."""
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        parts: list[str] = []
        for child in shape.shapes:
            parts.extend(_pptx_shape_text(child))
        return parts
    if getattr(shape, "has_table", False):
        rows: list[str] = []
        for row in shape.table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                rows.append(" | ".join(cells))
        return rows
    if getattr(shape, "has_text_frame", False):
        text = shape.text.strip()
        return [text] if text else []
    return []


def _extract_pptx(content: bytes) -> str:
    from pptx import Presentation

    presentation = Presentation(io.BytesIO(content))
    slides: list[str] = []
    for index, slide in enumerate(presentation.slides, start=1):
        parts: list[str] = []
        for shape in slide.shapes:
            parts.extend(_pptx_shape_text(shape))
        if parts:
            slides.append(f"[幻灯片 {index}]\n" + "\n".join(parts))
    return "\n\n".join(slides)


def _xlsx_cell(value: object) -> str:
    """单元格 → 单行文本（`|` / 换行转义，避免破坏 markdown 表格）。"""
    if value is None:
        return ""
    return str(value).strip().replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _extract_xlsx(content: bytes) -> str:
    """xlsx → 每个 sheet 一个 markdown 表格（sheet 名 + 表头 + 行）。

    read_only + data_only：大文件低内存；公式取 Excel 缓存值（无缓存值则为空）。
    首行视为表头（空表头回退列号 A/B/…），其余为数据行。
    """
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    sheets: list[str] = []
    try:
        for sheet in workbook.worksheets:
            rows: list[list[object]] = []
            for row in sheet.iter_rows(values_only=True):
                if any(cell is not None and str(cell).strip() for cell in row):
                    rows.append(list(row))
            if not rows:
                continue
            width = max(len(row) for row in rows)
            first = rows[0]
            header = [_xlsx_cell(first[i] if i < len(first) else "") for i in range(width)]
            header = [h or (chr(65 + i) if i < 26 else f"列{i + 1}") for i, h in enumerate(header)]
            lines = [
                f"## {sheet.title or 'Sheet'}",
                "| " + " | ".join(header) + " |",
                "| " + " | ".join(["---"] * width) + " |",
            ]
            for row in rows[1:]:
                cells = [_xlsx_cell(row[i] if i < len(row) else "") for i in range(width)]
                lines.append("| " + " | ".join(cells) + " |")
            sheets.append("\n".join(lines))
    finally:
        workbook.close()
    return "\n\n".join(sheets)


def extract_text(content: bytes, *, file_name: str | None, mime: str | None) -> ExtractionResult:
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
        elif ext == "pptx" or mime == _PPTX_MIME:
            text = _extract_pptx(content)
        elif ext == "xlsx" or mime == _XLSX_MIME:
            text = _extract_xlsx(content)
        else:
            unsupported_message = (
                "当前 .ppt 格式暂不支持自动提取（文件已落盘，请人工补全内容）"
                if ext == "ppt"
                else (
                    "旧版 .xls 暂不支持自动提取（文件已落盘），请另存为 .xlsx 后重新上传"
                    if ext == "xls"
                    else f"暂不支持从 .{ext or '该类型'} 文件抽取文本（文件已落盘，请人工补全内容）"
                )
            )
            return ExtractionResult(
                text="",
                status="unsupported",
                error_type="extraction_unsupported",
                error_message=unsupported_message,
                char_count=0,
            )
    except Exception as exc:  # noqa: BLE001 — 损坏 / 格式不符文件：降级为 failed，不崩溃
        safe_log_exception(
            _logger, "extraction_failed", exc, include_summary=False, level=logging.WARNING
        )
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
        text=text,
        status="extracted",
        error_type=None,
        error_message=None,
        char_count=len(text),
    )

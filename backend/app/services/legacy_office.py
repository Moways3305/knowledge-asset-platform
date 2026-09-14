"""Convert legacy Office in the resource-limited extraction process, never in HTTP."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.services.extraction_errors import _ControlledExtractionError

CONVERSION_TIMEOUT_SECONDS = 30
MAX_CONVERTED_BYTES = 100_000_000
logger = logging.getLogger(__name__)


def convert_legacy_office(content: bytes, extension: str) -> tuple[bytes, str]:
    if extension not in {"doc", "ppt", "xls"}:
        raise ValueError("unsupported conversion type")
    # DOC may contain RTF. Other mislabeled formats must not be silently imported.
    if not content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1") and not (
        extension == "doc" and content.lstrip().startswith(b"{\\rtf")
    ):
        raise _ControlledExtractionError(
            "extraction_format_mismatch",
            "文件内容与 Office 扩展名不匹配，请另存为正确格式后上传。",
        )
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if executable is None and os.name == "nt":
        candidate = Path("C:/Program Files/LibreOffice/program/soffice.com")
        if candidate.is_file():
            executable = str(candidate)
    if executable is None:
        raise _ControlledExtractionError(
            "office_converter_unavailable",
            "旧版 Office 转换服务未安装，原件已保留，请管理员更新处理镜像。",
        )
    target, output_filter = {
        "doc": ("docx", "Office Open XML Text"),
        "ppt": ("pptx", "Impress MS PowerPoint 2007 XML"),
        "xls": ("xlsx", "Calc MS Excel 2007 XML"),
    }[extension]
    with tempfile.TemporaryDirectory(prefix="kap-office-") as directory:
        root = Path(directory)
        profile = root / "profile"
        user = profile / "user"
        user.mkdir(parents=True)
        # No trusted macro locations; never execute source-document macros.
        (user / "registrymodifications.xcu").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
            "</item></oor:items>",
            encoding="utf-8",
        )
        source = root / f"source.{extension}"
        source.write_bytes(content)
        diagnostics = root / "converter.stderr"
        try:
            diagnostic_stream = diagnostics.open("wb")
            result = subprocess.run(
                [
                    executable,
                    f"-env:UserInstallation={profile.as_uri()}",
                    "--headless",
                    "--nologo",
                    "--nodefault",
                    "--norestore",
                    "--convert-to",
                    f"{target}:{output_filter}",
                    "--outdir",
                    str(root),
                    str(source),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=diagnostic_stream,
                timeout=CONVERSION_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise _ControlledExtractionError(
                "office_conversion_timeout",
                "Office 转换超时，请另存为新版格式后重试。",
            ) from exc
        except OSError as exc:
            raise _ControlledExtractionError(
                "office_converter_unavailable",
                "旧版 Office 转换服务无法启动，请管理员检查处理镜像。",
            ) from exc
        finally:
            if "diagnostic_stream" in locals():
                diagnostic_stream.close()
        converted = root / f"source.{target}"
        if result.returncode < 0:
            raise _ControlledExtractionError(
                "extraction_process_terminated",
                "文件转换进程被终止，原件已保留，请管理员检查内存与进程资源。",
            )
        if result.returncode != 0 or not converted.is_file():
            with diagnostics.open("rb") as stream:
                diagnostic = stream.read(65536).lower()
            memory_failure = any(
                marker in diagnostic
                for marker in (
                    b"bad_alloc",
                    b"cannot allocate memory",
                    b"out of memory",
                    b"failed to map segment",
                )
            )
            # Log only technical categories, never document content or raw stderr.
            logger.warning(
                "office_conversion_failed format=%s returncode=%s output_present=%s memory_failure=%s",
                extension,
                result.returncode,
                converted.is_file(),
                memory_failure,
            )
            if memory_failure:
                raise _ControlledExtractionError(
                    "extraction_memory_limit", "Office 转换达到内存限制，请管理员检查处理资源。"
                )
            raise _ControlledExtractionError(
                "office_conversion_failed",
                "Office 转换失败，请重试或另存为新版格式。",
            )
        if converted.stat().st_size > MAX_CONVERTED_BYTES:
            raise _ControlledExtractionError(
                "extraction_structure_limit", "转换后文件超过安全处理上限，请拆分后重试。"
            )
        return converted.read_bytes(), target

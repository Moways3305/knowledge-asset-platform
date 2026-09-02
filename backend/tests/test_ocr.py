from __future__ import annotations

import io
from types import SimpleNamespace

import pytest
from PIL import Image

from app.services import ocr
from app.services.extraction import ExtractionPage, ExtractionResult


def _image() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (20, 20), "white").save(output, format="PNG")
    return output.getvalue()


def test_local_ocr_records_page_status_and_confidence(monkeypatch):
    tsv = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    tsv += "5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t92\t项目报告\n"
    monkeypatch.setattr(
        ocr.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=tsv.encode()),
    )
    extraction = ExtractionResult(
        text="",
        status="ocr_required",
        error_type=None,
        error_message=None,
        char_count=0,
        pages=(ExtractionPage(1, "", "ocr_required"),),
        source_kind="image",
    )

    result = ocr.recognize(_image(), extraction)

    assert result.status == "succeeded"
    assert result.confidence == 92
    assert result.pages[0].status == "succeeded"
    assert "{{page:1}}" in result.text


def test_local_ocr_low_confidence_is_not_success(monkeypatch):
    tsv = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    tsv += "5\t1\t1\t1\t1\t1\t0\t0\t1\t1\t10\t模糊\n"
    monkeypatch.setattr(
        ocr.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=tsv.encode()),
    )
    extraction = ExtractionResult(
        text="",
        status="ocr_required",
        error_type=None,
        error_message=None,
        char_count=0,
        pages=(ExtractionPage(1, "", "ocr_required"),),
        source_kind="image",
    )

    result = ocr.recognize(_image(), extraction)

    assert result.status == "low_confidence"
    assert result.error_type == "ocr_low_confidence"


def test_ocr_rejects_documents_over_page_limit_before_invoking_engine(monkeypatch):
    monkeypatch.setattr(ocr, "MAX_OCR_PAGES", 1)
    extraction = ExtractionResult(
        text="",
        status="ocr_required",
        error_type=None,
        error_message=None,
        char_count=0,
        pages=(
            ExtractionPage(1, "", "ocr_required"),
            ExtractionPage(2, "", "ocr_required"),
        ),
        source_kind="pdf",
    )
    with pytest.raises(ocr.OCRError) as caught:
        ocr.recognize(b"ignored", extraction)
    assert caught.value.code == "ocr_page_limit"


def test_ocr_rejects_image_pixel_expansion(monkeypatch):
    monkeypatch.setattr(ocr, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(ocr.OCRError) as caught:
        ocr._image_bytes(_image(), source_kind="image", page_number=1)
    assert caught.value.code == "ocr_structure_limit"


def test_ocr_raster_timeout_kills_worker(monkeypatch):
    class HungProcess:
        returncode = None

        def __init__(self):
            self.killed = False
            self.communications = 0

        def communicate(self, *, input=None, timeout=None):
            self.communications += 1
            if self.communications == 1:
                raise ocr.subprocess.TimeoutExpired("raster", timeout)
            return b"", b""

        def kill(self):
            self.killed = True

    process = HungProcess()
    monkeypatch.setattr(ocr.subprocess, "Popen", lambda *args, **kwargs: process)

    with pytest.raises(ocr.OCRError) as caught:
        ocr._image_bytes(_image(), source_kind="image", page_number=1, timeout=0.1)

    assert caught.value.code == "ocr_timeout"
    assert process.killed is True

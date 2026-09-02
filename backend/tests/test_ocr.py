from __future__ import annotations

import io
import sys
from types import SimpleNamespace

import pytest
from PIL import Image

from app.services import ocr, ocr_raster_worker
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


def test_pdf_pixel_limit_is_checked_before_pixmap_allocation(monkeypatch):
    pixmap_called = False

    class Rect:
        x0 = 0
        y0 = 0
        x1 = 100
        y1 = 100

        def __mul__(self, matrix):
            return SimpleNamespace(
                x0=self.x0 * matrix.x,
                y0=self.y0 * matrix.y,
                x1=self.x1 * matrix.x,
                y1=self.y1 * matrix.y,
            )

    class Page:
        rect = Rect()

        def get_pixmap(self, **_kwargs):
            nonlocal pixmap_called
            pixmap_called = True
            raise AssertionError("pixmap allocation must not be attempted")

    class Document:
        page_count = 1

        def load_page(self, _index):
            return Page()

        def close(self):
            pass

    fake_fitz = SimpleNamespace(
        open=lambda **_kwargs: Document(),
        Matrix=lambda x, y: SimpleNamespace(x=x, y=y),
    )
    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

    with pytest.raises(ocr_raster_worker._RasterError) as caught:
        ocr_raster_worker._rasterize(b"pdf", source_kind="pdf", page_number=1, max_image_pixels=100)

    assert caught.value.code == "ocr_structure_limit"
    assert pixmap_called is False

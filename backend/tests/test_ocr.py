from __future__ import annotations

import io
from types import SimpleNamespace

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

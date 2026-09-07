"""Source modification date and confidentiality must not be silently fabricated."""

import json
import uuid

import pytest
from sqlalchemy import select

from app.api.ingest import _formed_on_for
from app.models.ingest import IngestTask, IngestTaskAiResult, UploadSessionItem
from app.seed.dev_seed import USER_CONSULTANT
from app.services.content_processing import _build_naming, process_content
from app.services.desensitization import NullDesensitizer
from app.services.extraction import ExtractionResult
from app.services.naming_advice import naming_preview_advice


@pytest.mark.parametrize(
    "level,confidence,expected", [("L2", "low", None), ("L4", "high", "L4"), (None, "low", None)]
)
def test_confidentiality_advice_has_no_fallback(level, confidence, expected):
    ai = IngestTaskAiResult(
        suggested_confidentiality_level=level,
        confidentiality_source="ai_content",
        confidentiality_confidence=confidence,
    )
    assert naming_preview_advice(ai)["suggested_confidentiality_level"] == expected
    assert naming_preview_advice(None)["suggested_confidentiality_level"] is None
    assert _build_naming("file_L2.txt", {}, None, "A2")["confidentiality_level"] is None


def test_no_filename_date_fallback():
    assert _formed_on_for({}, "report_20180801.docx") is None
    assert _formed_on_for({"report.docx": "2026-09-07"}, "report.docx") == "2026-09-07"


@pytest.mark.parametrize("confidence,expected", [("low", None), ("high", "L4")])
async def test_content_model_must_supply_reliable_confidentiality(confidence, expected):
    class Model:
        provider = "test"
        model = "test"

        async def chat_completion(self, messages, **kwargs):
            assert "不得默认 L2" in messages[0]["content"]
            return json.dumps(
                {
                    "topic": "公司介绍",
                    "one_liner": "介绍公司业务",
                    "detailed": "介绍公司业务与服务范围。",
                    "key_points": ["咨询服务"],
                    "confidentiality_level": "L4",
                    "confidentiality_confidence": confidence,
                }
            )

    draft, _ = await process_content(
        Model(),
        NullDesensitizer(),
        extraction=ExtractionResult("公司介绍与服务范围", "extracted", None, None, 10),
        file_name="source_L2.txt",
        trace_id=None,
    )
    assert draft["suggested_confidentiality_level"] == expected
    assert draft["naming_parsed_fields"]["confidentiality_level"] == expected


async def test_manifest_modification_date_survives_transport_and_ai_projection(client, db_session):
    headers = {"X-Dev-User-Id": str(USER_CONSULTANT)}
    session_id = str(uuid.uuid4())
    initialized = await client.post(
        "/api/v1/ingest/upload-sessions/init",
        headers=headers,
        json={
            "session_id": session_id,
            "total_transport_batches": 1,
            "manifest": [
                {
                    "client_file_key": "original",
                    "file_name": "report_20180801.txt",
                    "file_size": 6,
                    "transport_batch_index": 0,
                    "formed_on": "2026-09-07",
                }
            ],
        },
    )
    assert initialized.status_code == 200, initialized.text
    item_id = initialized.json()["items"][0]["id"]
    uploaded = await client.post(
        f"/api/v1/ingest/upload-sessions/{session_id}/batches",
        headers=headers,
        data={"batch_id": "batch-0", "batch_index": "0", "item_ids": f'["{item_id}"]'},
        files={"files": ("report_20180801.txt", b"report", "text/plain")},
    )
    assert uploaded.status_code == 200, uploaded.text
    item = await db_session.get(UploadSessionItem, uuid.UUID(item_id))
    assert item is not None and item.ingest_task_id is not None
    task_id = item.ingest_task_id
    result = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["suggested_formed_on"] == "2026-09-07"


@pytest.mark.parametrize("date", ["2026-09-08", None, "invalid"])
async def test_reselection_replaces_stale_manifest_date(client, db_session, date):
    headers = {"X-Dev-User-Id": str(USER_CONSULTANT)}
    session_id = str(uuid.uuid4())
    initialized = await client.post(
        "/api/v1/ingest/upload-sessions/init",
        headers=headers,
        json={
            "session_id": session_id,
            "total_transport_batches": 1,
            "manifest": [
                {
                    "client_file_key": "a",
                    "file_name": "report.txt",
                    "file_size": 6,
                    "transport_batch_index": 0,
                    "formed_on": "2018-08-01",
                }
            ],
        },
    )
    assert initialized.status_code == 200, initialized.text
    item_id = initialized.json()["items"][0]["id"]
    uploaded = await client.post(
        f"/api/v1/ingest/upload-sessions/{session_id}/items/{item_id}/bytes",
        headers=headers,
        data={"formed_on": date} if date else {},
        files={"file": ("report.txt", b"report", "text/plain")},
    )
    assert uploaded.status_code == 200, uploaded.text
    item = await db_session.get(UploadSessionItem, uuid.UUID(item_id))
    expected = "2026-09-08" if date == "2026-09-08" else None
    assert item.suggested_formed_on == expected
    task = await db_session.get(IngestTask, item.ingest_task_id)
    assert task.suggested_formed_on == expected
    result = await client.get(f"/api/v1/ingest/{task.id}/ai-result", headers=headers)
    assert result.json()["suggested_formed_on"] == expected


@pytest.mark.parametrize(
    "dates,expected",
    [
        (["2026-09-01", "2026-09-07"], ["2026-09-01", "2026-09-07"]),
        ([None, "2026-09-07"], [None, "2026-09-07"]),
        ({"same.txt": "2026-09-07"}, [None, None]),
    ],
)
async def test_legacy_upload_dates_follow_file_ordinals(client, db_session, dates, expected):
    response = await client.post(
        "/api/v1/ingest/upload-sessions",
        headers={"X-Dev-User-Id": str(USER_CONSULTANT)},
        data={"client_formed_on": json.dumps(dates)},
        files=[
            ("files", ("same.txt", b"first", "text/plain")),
            ("files", ("same.txt", b"second", "text/plain")),
        ],
    )
    assert response.status_code == 200, response.text
    items = (
        (
            await db_session.execute(
                select(UploadSessionItem)
                .where(UploadSessionItem.session_id == uuid.UUID(response.json()["id"]))
                .order_by(UploadSessionItem.ordinal)
            )
        )
        .scalars()
        .all()
    )
    assert [item.suggested_formed_on for item in items] == expected
    for item, date in zip(items, expected, strict=True):
        task = await db_session.get(IngestTask, item.ingest_task_id)
        assert task.suggested_formed_on == date

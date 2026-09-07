"""原文件修改日期仅来自客户端元数据，不以文件名日期兜底；另测预览类型。"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select

from app.models.ingest import IngestTask, UploadSessionItem
from app.seed.dev_seed import USER_CONSULTANT
from app.services.preview import _render_type_for
from app.services.upload_sessions import extract_formed_on_from_filename


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


# 历史解析工具仍可识别文件名日期，但不能作为上传修改日期的来源。
@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("方案-2026-07-30.xlsx", "2026-07-30"),
        ("需求文档20260730.txt", "2026-07-30"),
        ("2026年7月3日报告.docx", "2026-07-03"),
        ("报告_2026.1.5.pdf", "2026-01-05"),
        ("无日期文件.txt", None),
        ("report-2026-13-99.xlsx", None),
        ("", None),
    ],
)
def test_extract_formed_on_from_filename(file_name: str, expected: str | None):
    assert extract_formed_on_from_filename(file_name) == expected


# ---------------- 预览渲染类型 ----------------
@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("a.pdf", "pdf"),
        ("a.PDF", "pdf"),
        ("a.png", "image"),
        ("a.jpg", "image"),
        ("a.webp", "image"),
        ("a.md", "markdown"),
        ("a.markdown", "markdown"),
        ("a.txt", "text"),
        ("a.csv", "text"),
        ("a.json", "text"),
        ("a.docx", "office"),
        ("a.xlsx", "office"),
        ("a.pptx", "office"),
        ("a.xyz", None),
        ("noext", None),
    ],
)
def test_render_type_for(file_name: str, expected: str | None):
    assert _render_type_for(file_name) == expected


# ---------------- 单文件上传带 formed_on ----------------
async def test_single_upload_persists_client_formed_on(client, db_session):
    resp = await client.post(
        "/api/v1/ingest/upload",
        headers=_hdr(USER_CONSULTANT),
        files={"file": ("调研报告.txt", "内容".encode(), "text/plain")},
        data={"formed_on": "2026-07-30"},
    )
    assert resp.status_code == 200, resp.text
    task_id = uuid.UUID(resp.json()["ingest_task_id"])
    task = (
        await db_session.execute(select(IngestTask).where(IngestTask.id == task_id))
    ).scalar_one()
    assert task.suggested_formed_on == "2026-07-30"


async def test_single_upload_invalid_formed_on_ignored(client, db_session):
    resp = await client.post(
        "/api/v1/ingest/upload",
        headers=_hdr(USER_CONSULTANT),
        files={"file": ("调研报告.txt", "内容".encode(), "text/plain")},
        data={"formed_on": "not-a-date"},
    )
    assert resp.status_code == 200, resp.text
    task_id = uuid.UUID(resp.json()["ingest_task_id"])
    task = (
        await db_session.execute(select(IngestTask).where(IngestTask.id == task_id))
    ).scalar_one()
    assert task.suggested_formed_on is None


@pytest.mark.parametrize("metadata", [{}, {"formed_on": "invalid"}])
async def test_single_upload_without_valid_modified_date_does_not_infer_filename(
    client, db_session, metadata
):
    resp = await client.post(
        "/api/v1/ingest/upload",
        headers=_hdr(USER_CONSULTANT),
        files={"file": ("需求文档20260805.txt", "内容".encode(), "text/plain")},
        data=metadata,
    )
    assert resp.status_code == 200, resp.text
    task_id = uuid.UUID(resp.json()["ingest_task_id"])
    task = (
        await db_session.execute(select(IngestTask).where(IngestTask.id == task_id))
    ).scalar_one()
    assert task.suggested_formed_on is None


# ---------------- 批量上传（upload-sessions）带 client_formed_on ----------------
async def test_session_persists_client_formed_on(client, db_session):
    resp = await client.post(
        "/api/v1/ingest/upload-sessions",
        headers=_hdr(USER_CONSULTANT),
        files=[
            (
                "files",
                (
                    "方案表格.xlsx",
                    b"x",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
            )
        ],
        data={"client_formed_on": json.dumps({"方案表格.xlsx": "2026-07-29"})},
    )
    assert resp.status_code == 200, resp.text
    item = (
        await db_session.execute(
            select(UploadSessionItem).where(UploadSessionItem.file_name == "方案表格.xlsx")
        )
    ).scalar_one()
    task = (
        await db_session.execute(select(IngestTask).where(IngestTask.id == item.ingest_task_id))
    ).scalar_one()
    assert task.suggested_formed_on == "2026-07-29"


@pytest.mark.parametrize("metadata", [{}, {"client_formed_on": '["invalid"]'}])
async def test_session_without_valid_modified_date_does_not_infer_filename(
    client, db_session, metadata
):
    resp = await client.post(
        "/api/v1/ingest/upload-sessions",
        headers=_hdr(USER_CONSULTANT),
        files=[("files", ("需求文档20260730.txt", b"x", "text/plain"))],
        data=metadata,
    )
    assert resp.status_code == 200, resp.text
    item = (
        await db_session.execute(
            select(UploadSessionItem).where(UploadSessionItem.file_name == "需求文档20260730.txt")
        )
    ).scalar_one()
    task = (
        await db_session.execute(select(IngestTask).where(IngestTask.id == item.ingest_task_id))
    ).scalar_one()
    assert task.suggested_formed_on is None
    assert item.suggested_formed_on is None

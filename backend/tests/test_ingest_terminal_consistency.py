"""One upload keeps the same business outcome across confirmation and read models."""

import uuid

import pytest
from sqlalchemy import select
from test_project_ingest_approval import _hdr, _payload, _submit

from app.models.ingest import IngestTask
from app.models.review import ReviewTask
from app.seed.dev_seed import USER_CONSULTANT, USER_PROJECT_MANAGER
from app.services.workbench import _task_ref


@pytest.mark.parametrize("legacy_task_state", [None, "waiting_review"])
async def test_rejection_is_terminal_across_upload_status_pending_and_workbench(
    client, db_session, legacy_task_state
):
    task_id, review_id = await _submit(client, title="审核拒绝终态")
    response = await client.post(
        f"/api/v1/reviews/{review_id}/reject",
        headers=_hdr(USER_PROJECT_MANAGER),
        json={"review_comment": "请补充项目背景后重新上传"},
    )
    assert response.status_code == 200
    task = await db_session.get(IngestTask, uuid.UUID(task_id))
    if legacy_task_state:
        task.status = legacy_task_state
        await db_session.commit()

    uploads = (await client.get("/api/v1/ingest/my-uploads", headers=_hdr(USER_CONSULTANT))).json()
    item = next(item for item in uploads["items"] if item["task_id"] == task_id)
    assert item["processing_status"] == item["final_status"] == "rejected"
    assert item["review_comment"] == "请补充项目背景后重新上传"
    filtered = await client.get(
        "/api/v1/ingest/my-uploads?final_status=rejected", headers=_hdr(USER_CONSULTANT)
    )
    assert filtered.json()["total"] == 1
    pending = (await client.get("/api/v1/ingest/pending", headers=_hdr(USER_CONSULTANT))).json()
    row = next(row for row in pending["items"] if row["id"] == task_id)
    assert row["status"] == "rejected"
    assert row["can_batch_confirm"] is False and row["retryable"] is False
    assert row["review_comment"] == item["review_comment"]
    advice = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    assert advice.json()["status"] == "rejected"
    for method, suffix in [(client.get, "status"), (client.post, "retry")]:
        status = (
            await method(f"/api/v1/ingest/{task_id}/{suffix}", headers=_hdr(USER_CONSULTANT))
        ).json()
        assert status["stage"] != "failed"
        assert status["retryable"] is False
        assert status["next_action"] == {
            "key": "replace_file",
            "route_key": "upload",
            "enabled": True,
        }
        assert status["error"]["code"] == "review_rejected"
    overview = (
        await client.get("/api/v1/workbench/overview", headers=_hdr(USER_CONSULTANT))
    ).json()
    center = next(
        row
        for row in overview["task_center"]["my_tasks"]
        if row["task_ref"] == _task_ref("ingest", task_id)
    )
    assert center["status"] == "rejected"
    assert center["next_action_key"] == "replace_file"
    assert item["review_comment"] in center["result_summary"]
    counts = {row["key"]: row["count"] for row in overview["todos"]["items"]}
    assert counts.get("ingest_failed", 0) == 0
    assert counts["ingest_rejected"] == 1

    repeated = await client.post(
        f"/api/v1/ingest/{task_id}/confirm", headers=_hdr(USER_CONSULTANT), json=_payload("修改后")
    )
    assert repeated.status_code == 409
    assert "重新上传" in repeated.json()["detail"]["message"]
    db_session.expire_all()
    review = await db_session.get(ReviewTask, uuid.UUID(review_id))
    assert review.status == "rejected"
    assert review.confirmation_snapshot["title"] == "审核拒绝终态"
    assert (
        len(
            (
                await db_session.scalars(
                    select(ReviewTask).where(ReviewTask.source_ingest_task_id == uuid.UUID(task_id))
                )
            ).all()
        )
        == 1
    )


async def test_waiting_review_is_not_a_running_background_job(client):
    task_id, _ = await _submit(client)
    repeated = await client.post(
        f"/api/v1/ingest/{task_id}/confirm", headers=_hdr(USER_CONSULTANT), json=_payload()
    )
    assert repeated.status_code == 200 and repeated.json()["status"] == "waiting_review"
    center = (await client.get("/api/v1/workbench/overview", headers=_hdr(USER_CONSULTANT))).json()[
        "task_center"
    ]
    row = next(row for row in center["my_tasks"] if row["task_ref"] == _task_ref("ingest", task_id))
    assert row["status"] == "waiting_review" and row["next_action_label"] == "查看审核进度"
    assert not any(
        row["task_ref"] == _task_ref("ingest", task_id) for row in center["running_jobs"]
    )


@pytest.mark.parametrize("state", ["cancelled", "duplicate_skipped"])
async def test_terminal_uploads_stop_polling_and_cannot_be_confirmed(client, db_session, state):
    task_id, review_id = await _submit(client)
    task = await db_session.get(IngestTask, uuid.UUID(task_id))
    task.status = state
    if state == "cancelled":
        review = await db_session.get(ReviewTask, uuid.UUID(review_id))
        review.status = "cancelled"
    await db_session.commit()
    status = (
        await client.get(f"/api/v1/ingest/{task_id}/status", headers=_hdr(USER_CONSULTANT))
    ).json()
    assert status["status"] in {"completed", "cancelled"}
    assert status["retryable"] is False and status["next_action"]["enabled"] is False
    confirmed = await client.post(
        f"/api/v1/ingest/{task_id}/confirm", headers=_hdr(USER_CONSULTANT), json=_payload()
    )
    assert confirmed.status_code == 409


@pytest.mark.parametrize(
    "error_type,retryable",
    [("extraction_empty", False), ("extraction_corrupt", False), ("processing_error", True)],
)
async def test_failure_retry_advice_matches_actual_status_contract(
    client, db_session, error_type, retryable
):
    task = IngestTask(
        source="path_b_upload",
        source_file_ref="internal://test-missing.txt",
        source_file_name="failure.txt",
        status="failed",
        error_type=error_type,
        created_by=USER_CONSULTANT,
    )
    db_session.add(task)
    await db_session.commit()
    pending = (await client.get("/api/v1/ingest/pending", headers=_hdr(USER_CONSULTANT))).json()[
        "items"
    ]
    row = next(row for row in pending if row["id"] == str(task.id))
    assert row["retryable"] is retryable
    center = (await client.get("/api/v1/workbench/overview", headers=_hdr(USER_CONSULTANT))).json()[
        "task_center"
    ]
    item = next(
        row for row in center["my_tasks"] if row["task_ref"] == _task_ref("ingest", task.id)
    )
    assert item["next_action_label"] == ("重试处理" if retryable else "重新上传")


@pytest.mark.parametrize("error_type", ["extraction_empty", "extraction_corrupt"])
async def test_session_does_not_offer_or_accept_retry_for_replace_file_failure(
    client, db_session, error_type
):
    response = await client.post(
        "/api/v1/ingest/upload-sessions",
        headers=_hdr(USER_CONSULTANT),
        files={"files": ("corrupt.txt", b"readable fixture", "text/plain")},
    )
    assert response.status_code == 200
    value = response.json()
    item = value["items"][0]
    task = await db_session.get(IngestTask, uuid.UUID(item["ingest_task_id"]))
    task.status = "failed"
    task.error_type = error_type
    await db_session.commit()
    refreshed = await client.get(
        f"/api/v1/ingest/upload-sessions/{value['id']}", headers=_hdr(USER_CONSULTANT)
    )
    assert refreshed.json()["items"][0]["retryable"] is False
    retry = await client.post(
        f"/api/v1/ingest/upload-sessions/{value['id']}/items/{item['id']}/retry",
        headers=_hdr(USER_CONSULTANT),
    )
    assert retry.status_code == 409
    assert "重新上传" in retry.json()["detail"]["message"]

"""First-party ingest task status and recovery contract tests."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select

from app.main import app
from app.models.ingest import IngestTask, IngestTaskAiResult
from app.models.knowledge import KnowledgeAssetVersion
from app.models.review import ReviewTask
from app.schemas.permission import CallerContext
from app.seed.dev_seed import (
    KA_PERSONAL,
    PROJECT_ALPHA,
    USER_CONSULTANT,
    USER_PROJECT_MANAGER,
)
from app.services.desensitization import NullDesensitizer
from app.services.generation_models import get_generation_llm_client
from app.services.ingest_status import retry_task
from app.services.llm_client import NullLLMClient
from app.services.storage import LocalFileStorage
from app.services.weknora_client import NullWeKnoraClient


def _headers(user_id):
    return {"X-Dev-User-Id": str(user_id)}


def _status_url(task_id) -> str:
    return f"/api/v1/ingest/{task_id}/status"


def _retry_url(task_id) -> str:
    return f"/api/v1/ingest/{task_id}/retry"


async def _task(db_session, *, status, processing_stage=None, error_type=None, asset_id=None):
    task = IngestTask(
        source="path_b_upload",
        source_file_ref=f"server-only/{uuid.uuid4()}.txt",
        source_file_name="status-test.txt",
        source_file_mime_type="text/plain",
        status=status,
        processing_stage=processing_stage,
        error_type=error_type,
        error_message="SECRET-LIKE provider response",
        created_by=USER_CONSULTANT,
        result_asset_id=asset_id,
    )
    db_session.add(task)
    await db_session.commit()
    return task


async def test_upload_extraction_and_generation_stages_are_distinct(client, db_session):
    cases = [
        ("pending", "upload_saved", "upload_saved"),
        ("processing", "text_extraction", "text_extraction"),
        (
            "processing",
            "canonical_markdown_generation",
            "canonical_markdown_generation",
        ),
        ("processing", "content_generation", "content_generation"),
    ]
    for raw_status, processing_stage, expected_stage in cases:
        task = await _task(db_session, status=raw_status, processing_stage=processing_stage)
        response = await client.get(_status_url(task.id), headers=_headers(USER_CONSULTANT))
        assert response.status_code == 200
        body = response.json()
        assert body["stage"] == expected_stage
        assert body["status"] == "processing"
        assert body["next_action"] == {"key": "wait", "route_key": None, "enabled": False}


async def test_generated_draft_waits_for_confirmation(client, db_session):
    task = await _task(db_session, status="pending_confirmation")
    task.ai_result = IngestTaskAiResult(
        ingest_task_id=task.id,
        extraction_status="extracted",
        naming_parsed_fields={"generation_status": "generated", "summary_generated": True},
        llm_provider="trusted-provider",
    )
    await db_session.commit()

    response = await client.get(_status_url(task.id), headers=_headers(USER_CONSULTANT))

    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "awaiting_confirmation"
    assert body["status"] == "action_required"
    assert body["retryable"] is False
    assert body["next_action"]["key"] == "review_and_confirm"
    assert body["error"] is None


@pytest.mark.parametrize("category", ["response_error", "timeout"])
async def test_transient_generation_failures_are_retryable(client, db_session, category):
    task = await _task(db_session, status="pending_confirmation")
    task.ai_result = IngestTaskAiResult(
        ingest_task_id=task.id,
        extraction_status="extracted",
        naming_parsed_fields={
            "generation_status": "failed",
            "generation_error_category": category,
        },
    )
    await db_session.commit()

    response = await client.get(_status_url(task.id), headers=_headers(USER_CONSULTANT))

    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "degraded_complete"
    assert body["status"] == "degraded"
    assert body["retryable"] is True
    assert body["next_action"]["key"] == "retry_processing"


async def test_non_transient_generation_failure_is_not_retryable(client, db_session):
    task = await _task(db_session, status="pending_confirmation")
    task.ai_result = IngestTaskAiResult(
        ingest_task_id=task.id,
        extraction_status="extracted",
        naming_parsed_fields={
            "generation_status": "failed",
            "generation_error_category": "model_unavailable",
        },
    )
    await db_session.commit()

    response = await client.get(_status_url(task.id), headers=_headers(USER_CONSULTANT))

    assert response.status_code == 200
    body = response.json()
    assert body["retryable"] is False
    assert body["next_action"]["key"] == "review_and_confirm"


async def test_llm_failure_is_degraded_and_never_echoes_provider_details(client, db_session):
    task = await _task(db_session, status="pending_confirmation")
    task.ai_result = IngestTaskAiResult(
        ingest_task_id=task.id,
        extraction_status="extracted",
        naming_parsed_fields={
            "generation_status": "failed",
            "provider_error": "SECRET-LIKE sk-live https://provider.invalid/payload",
        },
        llm_provider="SECRET-LIKE-provider",
        llm_model="internal-model-id",
    )
    await db_session.commit()

    response = await client.get(_status_url(task.id), headers=_headers(USER_CONSULTANT))

    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "degraded_complete"
    assert body["status"] == "degraded"
    assert body["error"]["code"] == "content_generation_unavailable"
    assert body["next_action"]["key"] == "review_and_confirm"
    for token in ("SECRET-LIKE", "sk-live", "provider.invalid", "internal-model-id"):
        assert token not in response.text


async def test_unsupported_and_failed_files_have_safe_distinct_recovery(client, db_session):
    unsupported = await _task(db_session, status="pending_confirmation")
    unsupported.ai_result = IngestTaskAiResult(
        ingest_task_id=unsupported.id,
        extraction_status="unsupported",
        naming_parsed_fields={"generation_status": "failed"},
    )
    failed = await _task(db_session, status="failed", error_type="extraction_failed")
    empty = await _task(db_session, status="failed", error_type="extraction_empty")
    await db_session.commit()

    unsupported_body = (
        await client.get(_status_url(unsupported.id), headers=_headers(USER_CONSULTANT))
    ).json()
    failed_body = (
        await client.get(_status_url(failed.id), headers=_headers(USER_CONSULTANT))
    ).json()
    empty_body = (await client.get(_status_url(empty.id), headers=_headers(USER_CONSULTANT))).json()

    assert unsupported_body["error"]["code"] == "file_format_unsupported"
    assert unsupported_body["next_action"]["key"] == "review_and_confirm"
    assert failed_body["error"]["code"] == "file_parse_failed"
    assert failed_body["next_action"]["key"] == "replace_file"
    assert empty_body["error"]["code"] == "file_text_unavailable"
    assert "SECRET-LIKE" not in str((unsupported_body, failed_body, empty_body))


async def test_review_confirmation_stage_is_visible_to_submitter_and_reviewer(client, db_session):
    task = await _task(db_session, status="waiting_review")
    review = ReviewTask(
        review_type="project_ingest_approval",
        trigger_source="path_b_upload",
        source_ingest_task_id=task.id,
        target_project_id=PROJECT_ALPHA,
        target_scope="project",
        status="pending_reviewer",
        reviewer_user_id=USER_PROJECT_MANAGER,
        submitted_by=USER_CONSULTANT,
        confirmation_snapshot={},
    )
    db_session.add(review)
    await db_session.commit()

    for user_id in (USER_CONSULTANT, USER_PROJECT_MANAGER):
        response = await client.get(_status_url(task.id), headers=_headers(user_id))
        assert response.status_code == 200
        body = response.json()
        assert body["stage"] == "confirmation"
        assert body["status"] == "waiting"
        assert body["review_id"] == str(review.id)
        assert body["next_action"]["key"] == "view_review"


async def test_index_queue_processing_completion_failure_and_degradation(client, db_session):
    task = await _task(db_session, status="completed", asset_id=KA_PERSONAL)
    version = (
        await db_session.execute(
            select(KnowledgeAssetVersion).where(
                KnowledgeAssetVersion.asset_id == KA_PERSONAL,
                KnowledgeAssetVersion.version_status == "active",
            )
        )
    ).scalar_one()

    states = [
        ("not_indexed", None, "indexing_queued", "processing"),
        ("indexing", None, "indexing_in_progress", "processing"),
        ("indexing", "pending", "indexing_in_progress", "processing"),
        ("indexing", "processing", "indexing_in_progress", "processing"),
        ("indexed", "completed", "completed", "completed"),
        ("skipped", None, "degraded_complete", "degraded"),
        ("index_failed", "failed", "failed", "failed"),
    ]
    for index_status, parse_status, expected_stage, expected_status in states:
        version.index_status = index_status
        version.weknora_parse_status = parse_status
        version.index_error_code = "SECRET-LIKE" if index_status == "index_failed" else None
        await db_session.commit()
        response = await client.get(_status_url(task.id), headers=_headers(USER_CONSULTANT))
        assert response.status_code == 200
        body = response.json()
        assert body["stage"] == expected_stage
        assert body["status"] == expected_status
        assert "SECRET-LIKE" not in response.text
    assert body["error"]["code"] == "weknora_parse_failed"
    assert body["retryable"] is True
    assert body["next_action"]["key"] == "reparse"


async def test_unauthorized_task_and_missing_task_are_indistinguishable(client, db_session):
    task = await _task(db_session, status="pending_confirmation")
    missing_id = uuid.uuid4()

    denied = await client.get(_status_url(task.id), headers=_headers(USER_PROJECT_MANAGER))
    missing = await client.get(_status_url(missing_id), headers=_headers(USER_PROJECT_MANAGER))

    assert denied.status_code == missing.status_code == 404
    assert (
        denied.json()
        == missing.json()
        == {
            "detail": {
                "denied_reason": "ingest_task_not_found",
                "message": "入库任务不存在或不可见",
            }
        }
    )

    denied_retry = await client.post(_retry_url(task.id), headers=_headers(USER_PROJECT_MANAGER))
    missing_retry = await client.post(
        _retry_url(missing_id), headers=_headers(USER_PROJECT_MANAGER)
    )
    assert denied_retry.status_code == missing_retry.status_code == 404
    assert denied_retry.json() == missing_retry.json() == denied.json()


async def test_processing_failure_can_be_retried_without_leaking_storage(client, db_session):
    app.dependency_overrides[get_generation_llm_client] = lambda: NullLLMClient()
    content = b"retryable text content"
    ref = client._kap_storage.save(content, original_name="retry.txt")
    task = IngestTask(
        source="path_b_upload",
        source_file_ref=ref,
        source_file_name="retry.txt",
        source_file_mime_type="text/plain",
        status="failed",
        error_type="processing_error",
        error_message="SECRET-LIKE storage failure",
        retry_count=3,
        max_retries=3,
        created_by=USER_CONSULTANT,
    )
    db_session.add(task)
    await db_session.commit()

    before = await client.get(_status_url(task.id), headers=_headers(USER_CONSULTANT))
    retried = await client.post(_retry_url(task.id), headers=_headers(USER_CONSULTANT))

    assert before.json()["retryable"] is True
    assert before.json()["error"]["code"] == "ingest_processing_failed"
    assert retried.status_code == 200
    assert retried.json()["stage"] == "waiting_generation_config"
    assert retried.json()["next_action"]["key"] == "retry_generation"
    assert retried.json()["next_action"]["enabled"] is False
    assert ref not in retried.text
    assert "SECRET-LIKE" not in retried.text


async def test_processing_failure_waiting_for_retry_is_actionable(client, db_session):
    task = await _task(
        db_session,
        status="processing",
        processing_stage="text_extraction",
        error_type="processing_error",
    )

    response = await client.get(_status_url(task.id), headers=_headers(USER_CONSULTANT))

    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "failed"
    assert body["status"] == "failed"
    assert body["retryable"] is True
    assert body["next_action"]["key"] == "retry_processing"


async def test_duplicate_retry_while_processing_enqueues_once(client, db_session, monkeypatch):
    task = await _task(db_session, status="failed", error_type="processing_error")
    task.source_file_ref = client._kap_storage.save(b"retry source", original_name="retry.txt")
    await db_session.commit()
    calls = 0

    async def _fake_enqueue(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return "processing"

    monkeypatch.setattr("app.services.ingest_status.enqueue_ingest_processing", _fake_enqueue)

    first = await client.post(_retry_url(task.id), headers=_headers(USER_CONSULTANT))
    second = await client.post(_retry_url(task.id), headers=_headers(USER_CONSULTANT))

    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == second.json()["status"] == "processing"
    assert calls == 1


async def test_concurrent_retry_with_independent_sessions_enqueues_once(
    sessionmaker_fixture, db_session, tmp_path, monkeypatch
):
    task = await _task(db_session, status="failed", error_type="processing_error")
    caller = CallerContext(
        user_id=USER_CONSULTANT,
        is_active=True,
        active_company_roles={"consultant"},
        active_project_ids={PROJECT_ALPHA},
        active_project_roles={PROJECT_ALPHA: "consultant"},
    )
    storage = LocalFileStorage(tmp_path / "concurrent-retry")
    task.source_file_ref = storage.save(b"retry source", original_name="retry.txt")
    await db_session.commit()
    loaded = 0
    both_loaded = asyncio.Event()
    enqueue_calls = 0

    import app.services.ingest_status as status_service

    original_load = status_service._load_context

    async def _load_after_barrier(*args, **kwargs):
        nonlocal loaded
        context = await original_load(*args, **kwargs)
        loaded += 1
        if loaded == 2:
            both_loaded.set()
        await asyncio.wait_for(both_loaded.wait(), timeout=2)
        return context

    async def _fake_enqueue(*_args, **_kwargs):
        nonlocal enqueue_calls
        enqueue_calls += 1
        return "processing"

    monkeypatch.setattr(status_service, "_load_context", _load_after_barrier)
    monkeypatch.setattr(status_service, "enqueue_ingest_processing", _fake_enqueue)

    async with sessionmaker_fixture() as first, sessionmaker_fixture() as second:
        responses = await asyncio.gather(
            retry_task(
                first,
                caller,
                task.id,
                storage=storage,
                llm=NullLLMClient(),
                desensitizer=NullDesensitizer(),
                weknora=NullWeKnoraClient(),
                trace_id="concurrent-first",
            ),
            retry_task(
                second,
                caller,
                task.id,
                storage=storage,
                llm=NullLLMClient(),
                desensitizer=NullDesensitizer(),
                weknora=NullWeKnoraClient(),
                trace_id="concurrent-second",
            ),
        )

    assert enqueue_calls == 1
    assert {response.status.value for response in responses} == {"processing"}


async def test_ocr_retry_rejects_zero_byte_source_before_claim(client, db_session, monkeypatch):
    ref = client._kap_storage.save(b"source", original_name="scan.pdf")
    task = IngestTask(
        source="path_b_upload",
        source_file_ref=ref,
        source_file_name="scan.pdf",
        source_file_mime_type="application/pdf",
        status="failed",
        processing_stage="ocr_failed",
        error_type="ocr_timeout",
        retry_count=2,
        created_by=USER_CONSULTANT,
    )
    db_session.add(task)
    await db_session.commit()
    client._kap_storage.resolve_path(ref).write_bytes(b"")
    enqueue_calls = 0

    async def _fake_enqueue(*_args, **_kwargs):
        nonlocal enqueue_calls
        enqueue_calls += 1
        return "processing"

    monkeypatch.setattr("app.services.ingest_status.enqueue_ingest_processing", _fake_enqueue)

    response = await client.post(_retry_url(task.id), headers=_headers(USER_CONSULTANT))

    assert response.status_code == 409
    assert response.json()["detail"]["denied_reason"] == "ingest_source_unavailable"
    assert enqueue_calls == 0
    await db_session.refresh(task)
    assert task.status == "failed"
    assert task.processing_stage == "ocr_failed"
    assert task.retry_count == 2


async def test_index_failure_retry_reuses_authorized_index_contract(client, db_session):
    task = await _task(db_session, status="completed", asset_id=KA_PERSONAL)
    version = (
        await db_session.execute(
            select(KnowledgeAssetVersion).where(
                KnowledgeAssetVersion.asset_id == KA_PERSONAL,
                KnowledgeAssetVersion.version_status == "active",
            )
        )
    ).scalar_one()
    version.index_status = "index_failed"
    version.weknora_parse_status = "failed"
    version.index_error_code = "weknora_call_failed"
    await db_session.commit()

    response = await client.post(_retry_url(task.id), headers=_headers(USER_CONSULTANT))

    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "failed"
    assert body["status"] == "failed"
    assert body["error"]["code"] == "weknora_parse_failed"
    assert "weknora_kb_id" not in response.text
    assert "source_file_ref" not in response.text


async def test_parse_failure_keeps_indexed_state_and_exposes_reparse_action(client, db_session):
    task = await _task(db_session, status="completed", asset_id=KA_PERSONAL)
    version = (
        await db_session.execute(
            select(KnowledgeAssetVersion).where(
                KnowledgeAssetVersion.asset_id == KA_PERSONAL,
                KnowledgeAssetVersion.version_status == "active",
            )
        )
    ).scalar_one()
    version.index_status = "indexed"
    version.weknora_doc_id = "server-only-doc"
    version.weknora_parse_status = "failed"
    await db_session.commit()

    response = await client.get(_status_url(task.id), headers=_headers(USER_CONSULTANT))

    assert response.status_code == 200
    body = response.json()
    assert body["stage"] == "failed"
    assert body["status"] == "failed"
    assert body["error"]["code"] == "weknora_parse_failed"
    assert body["next_action"] == {
        "key": "reparse",
        "route_key": "ingest_task_retry",
        "enabled": True,
    }
    await db_session.refresh(version)
    assert version.index_status == "indexed"
    assert "server-only-doc" not in response.text


async def test_status_response_field_whitelist(client, db_session):
    task = await _task(db_session, status="failed", error_type="processing_error")
    response = await client.get(_status_url(task.id), headers=_headers(USER_CONSULTANT))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "task_id",
        "stage",
        "status",
        "updated_at",
        "retryable",
        "next_action",
        "error",
        "result_asset_id",
        "review_id",
    }
    assert set(body["next_action"]) == {"key", "route_key", "enabled"}
    assert set(body["error"]) == {"code", "message", "recovery_hint"}
    for token in (
        "source_file_ref",
        "storage_ref",
        "weknora_kb_id",
        "weknora_doc_id",
        "api_key",
        "provider",
        "model_id",
        "SECRET-LIKE",
    ):
        assert token not in response.text

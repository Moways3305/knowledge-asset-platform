from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.models.ingest import IngestTask, IngestTaskAiResult
from app.schemas.bulk_operations import (
    BulkItemResult,
    KnowledgeBulkDeleteRequest,
    ReviewBulkActionRequest,
)
from app.schemas.ingest import (
    IngestBulkConfirmItem,
    IngestBulkConfirmRequest,
    IngestConfirmRequest,
)
from app.services.bulk_operations import execute_in_controlled_batches, terminal_response
from app.services.ingest import _suggestion_generation_state


def _task(*, status: str = "pending_confirmation") -> IngestTask:
    return IngestTask(
        source="path_b_upload",
        source_file_ref="server-only",
        source_file_name="safe.txt",
        status=status,
    )


def test_suggestion_generation_states_use_persisted_processing_facts() -> None:
    generated_ai = IngestTaskAiResult(
        suggested_title="建议标题",
        suggested_summary="建议摘要",
        llm_provider="configured",
        extraction_status="extracted",
        naming_parsed_fields={"summary_generated": True},
    )
    assert _suggestion_generation_state(_task(), generated_ai) == (
        "generated",
        "已提取正文并生成建议，请人工核对",
    )

    degraded_ai = IngestTaskAiResult(
        suggested_title="规则标题",
        llm_provider=None,
        extraction_status="extracted",
        naming_parsed_fields={},
    )
    status, reason = _suggestion_generation_state(_task(), degraded_ai)
    assert status == "needs_correction"
    assert "未完整生成" in reason

    unsupported_ai = IngestTaskAiResult(extraction_status="unsupported")
    status, reason = _suggestion_generation_state(_task(status="failed"), unsupported_ai)
    assert status == "needs_manual_completion"
    assert "格式暂不支持" in reason
    assert "server-only" not in reason


def test_bulk_contract_rejects_duplicates_and_empty_reject_reason() -> None:
    item_id = uuid.uuid4()
    with pytest.raises(ValidationError):
        KnowledgeBulkDeleteRequest(
            item_ids=[item_id, item_id],
            scope="personal",
        )
    with pytest.raises(ValidationError):
        ReviewBulkActionRequest(
            item_ids=[item_id],
            action="reject",
            review_comment=" ",
        )


def test_transport_limit_stays_bounded_without_becoming_a_logical_bulk_limit() -> None:
    item_ids = [uuid.uuid4() for _ in range(501)]
    with pytest.raises(ValidationError):
        KnowledgeBulkDeleteRequest(item_ids=item_ids, scope="personal")

    accepted = KnowledgeBulkDeleteRequest(
        item_ids=item_ids[:500],
        scope="personal",
        client_operation_id=uuid.uuid4(),
        request_index=2,
        request_count=3,
        total_submitted=1001,
    )
    assert len(accepted.item_ids) == 500
    assert accepted.total_submitted == 1001

    with pytest.raises(ValidationError):
        KnowledgeBulkDeleteRequest(
            item_ids=[uuid.uuid4()],
            scope="personal",
            client_operation_id=uuid.uuid4(),
        )

    confirmation = IngestConfirmRequest(
        title="批量入库",
        summary="安全摘要",
        target_scope="personal",
        asset_type="methodology",
        confidentiality_level="L2",
        ai_access_level="A2",
    )
    ingest_items = [
        IngestBulkConfirmItem(task_id=uuid.uuid4(), confirmation=confirmation) for _ in range(501)
    ]
    with pytest.raises(ValidationError):
        IngestBulkConfirmRequest(
            items=ingest_items,
            target_scope="personal",
        )


@pytest.mark.asyncio
async def test_large_bulk_executes_in_bounded_batches_and_returns_terminal_mode() -> None:
    item_ids = [uuid.uuid4() for _ in range(51)]
    observed_batches: list[list[uuid.UUID]] = []

    async def process_batch(batch: list[uuid.UUID]) -> list[BulkItemResult]:
        observed_batches.append(list(batch))
        return [BulkItemResult(item_id=item_id, status="succeeded") for item_id in batch]

    items = await execute_in_controlled_batches(item_ids, process_batch)
    result = terminal_response(
        uuid.uuid4(),
        item_ids,
        items,
    )
    assert [len(batch) for batch in observed_batches] == [50, 1]
    assert [item.item_id for item in items] == item_ids
    assert result.execution_mode == "controlled_batch"
    assert result.status == "completed"
    assert result.submitted == result.succeeded == 51
    assert result.skipped == result.failed == 0

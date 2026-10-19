"""D1 阶段4：子块召回 → 父文件全文给 Agent（Small-to-Big）函数级测试。"""

from __future__ import annotations

import asyncio
import logging
import uuid

import pytest

from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetChunk,
    KnowledgeAssetSummary,
    KnowledgeAssetVersion,
)
from app.schemas.permission import (
    AccessLayer,
    DeniedReason,
    EffectiveAccessSource,
    PermissionDecision,
)
from app.services import retrieval


def _decision(allowed: bool) -> PermissionDecision:
    return PermissionDecision(
        allowed=allowed,
        requested_layer=AccessLayer.original,
        allowed_layer=AccessLayer.original if allowed else AccessLayer.summary,
        denied_reason=DeniedReason.allowed if allowed else DeniedReason.original_requires_request,
        effective_access_source=EffectiveAccessSource.system_rule
        if allowed
        else EffectiveAccessSource.none,
        audit_required=False,
        strong_audit_required=False,
    )


def _asset(*, title: str = "测试资产", conf: str = "L1") -> KnowledgeAsset:
    asset = KnowledgeAsset(
        id=uuid.uuid4(),
        title=title,
        scope="project",
        zone="material",
        asset_type="document",
        owner_user_id=uuid.uuid4(),
        confidentiality_level=conf,
        ai_access_level="A1",
        asset_status="active",
        visibility="project_only",
    )
    asset.summaries = []
    asset.tags = []
    return asset


def _version(asset: KnowledgeAsset) -> KnowledgeAssetVersion:
    return KnowledgeAssetVersion(
        id=uuid.uuid4(),
        asset_id=asset.id,
        version_no="v1",
        version_status="active",
        created_by=uuid.uuid4(),
        index_status="indexed",
        weknora_doc_id=f"wk-doc-{asset.id}",
        weknora_kb_id="wk-kb",
    )


def _recalled(
    asset: KnowledgeAsset,
    version: KnowledgeAssetVersion,
    *,
    original_allowed: bool = True,
    summary_allowed: bool = True,
) -> retrieval.RecalledAsset:
    return retrieval.RecalledAsset(
        asset=asset,
        version=version,
        score=0.9,
        matched_chunks=[
            {
                "knowledge_id": version.weknora_doc_id,
                "seq": 0,
                "chunk_index": 0,
                "content": "命中片段内容",
            }
        ],
        discovery=_decision(True),
        summary=_decision(summary_allowed),
        original=_decision(original_allowed),
    )


class FakeDesens:
    """记录调用并可模拟擦洗失败。"""

    def __init__(self, result: str | None = "已擦洗全文"):
        self.result = result
        self.calls: list[str] = []

    async def scrub(self, text: str, *, trace_id: str | None = None) -> str | None:
        self.calls.append(text)
        return self.result


class CaptureLLM:
    """捕获喂给 LLM 的消息，固定返回答案。"""

    def __init__(self) -> None:
        self.messages: list[dict] | None = None

    async def chat_completion(
        self,
        messages,
        *,
        temperature: float = 0.2,
        model: str | None = None,
        json_object: bool = False,
        trace_id: str | None = None,
    ) -> str:
        self.messages = messages
        return "【答案】"


@pytest.mark.parametrize("parent", [True, False])
async def test_evidence_diagnostics_expose_only_stage_counts_and_timings(
    db_session, caplog, parent
):
    caplog.set_level(logging.INFO, logger="app.services.retrieval")
    asset = _asset(title="PRIVATE_TITLE", conf="L3")
    version = _version(asset)
    item = _recalled(asset, version)
    item.matched_chunks[0]["content"] = "PRIVATE_RAW_CHUNK"
    if parent:
        db_session.add_all([asset, version])
        db_session.add(
            KnowledgeAssetChunk(
                asset_id=asset.id,
                version_id=version.id,
                chunk_index=0,
                chunk_type="governance_text",
                content_text="PRIVATE_RAW_DOCUMENT",
                chunk_status="active",
            )
        )
        await db_session.commit()
    scrubber = FakeDesens("SAFE_EVIDENCE")
    result = (
        await retrieval.gather_parent_context(db_session, [item], scrubber, trace_id="safe-trace")
        if parent
        else await retrieval.gather_evidence([item], scrubber, trace_id="safe-trace")
    )
    assert [e.snippet for e in result] == ["SAFE_EVIDENCE"]
    stages = [r for r in caplog.records if r.message == "retrieval_evidence_stage"]
    expected_phase = "parent_documents" if parent else "fallback_chunks"
    record = next(r for r in stages if r.evidence_stage == expected_phase)
    assert record.stage_status == "complete"
    assert record.job_count == record.started_job_count == record.completed_job_count == 1
    assert record.evidence_count == 1 and record.duration_ms >= 0
    scrubs = [r for r in caplog.records if r.message == "retrieval_evidence_scrub"]
    assert len(scrubs) == 1
    assert scrubs[0].scrub_status == "complete"
    assert scrubs[0].content_chars == len(scrubber.calls[0])
    for record in stages + scrubs:
        assert record.trace_id == "safe-trace"
        emitted = repr(record.__dict__)
        for private in ("PRIVATE", "SAFE_EVIDENCE", str(asset.id), str(version.id)):
            assert private not in emitted


@pytest.mark.parametrize("result", [None, "SAFE"])
async def test_scrub_diagnostic_distinguishes_empty_result_without_exposing_content(caplog, result):
    caplog.set_level(logging.INFO, logger="app.services.retrieval")
    asset = _asset(title="PRIVATE_TITLE", conf="L4")
    assert (
        await retrieval._scrub_chunk(
            FakeDesens(result), asset, "PRIVATE_CONTENT", trace_id="safe-trace"
        )
        == result
    )
    record = next(r for r in caplog.records if r.message == "retrieval_evidence_scrub")
    assert record.scrub_status == ("complete" if result else "unavailable")
    assert record.content_chars == len("PRIVATE_CONTENT") and record.duration_ms >= 0
    assert "PRIVATE" not in repr(record.__dict__)


@pytest.mark.parametrize("parent", [True, False])
async def test_evidence_scrubs_overlap_but_stay_bounded_and_keep_citation_order(db_session, parent):
    started_two = asyncio.Event()
    started_three = asyncio.Event()
    releases = [asyncio.Event() for _ in range(3)]

    class ControlledScrub:
        active = 0
        peak = 0
        started = 0

        async def scrub(self, text, **kwargs):
            index = next(i for i in range(3) if f"RAW_{i}" in text)
            self.active += 1
            self.started += 1
            self.peak = max(self.peak, self.active)
            if self.active == 2:
                started_two.set()
            if self.started == 3:
                started_three.set()
            try:
                await releases[index].wait()
                return f"SAFE_{index}"
            finally:
                self.active -= 1

    recalled = []
    for index in range(3):
        asset = _asset(title=f"资料{index}", conf="L3")
        version = _version(asset)
        item = _recalled(asset, version)
        item.matched_chunks[0]["content"] = f"RAW_{index}"
        recalled.append(item)
        if parent:
            db_session.add_all([asset, version])
            db_session.add(
                KnowledgeAssetChunk(
                    asset_id=asset.id,
                    version_id=version.id,
                    chunk_index=0,
                    chunk_type="governance_text",
                    content_text=f"RAW_{index}",
                    chunk_status="active",
                )
            )
    await db_session.commit()
    scrubber = ControlledScrub()
    operation = (
        retrieval.gather_parent_context(db_session, recalled, scrubber, trace_id="bounded")
        if parent
        else retrieval.gather_evidence(recalled, scrubber, trace_id="bounded")
    )
    task = asyncio.create_task(operation)
    try:
        await asyncio.wait_for(started_two.wait(), timeout=1)
        releases[1].set()
        await asyncio.wait_for(started_three.wait(), timeout=1)
    finally:
        for release in releases:
            release.set()
        result = await task
    assert scrubber.peak == 2 and scrubber.active == 0
    assert [e.asset.id for e in result] == [r.asset.id for r in recalled]
    assert [e.snippet for e in result] == [f"SAFE_{i}" for i in range(3)]


async def test_fallback_uses_free_slot_without_waiting_for_unrelated_parent(db_session):
    parent_started = asyncio.Event()
    fallback_started = asyncio.Event()
    release_parent = asyncio.Event()

    class PipelineScrub:
        active = 0
        peak = 0

        async def scrub(self, text, **kwargs):
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                if text == "PARENT_0":
                    parent_started.set()
                    await release_parent.wait()
                elif text == "CHUNK_2":
                    fallback_started.set()
                return "SAFE_" + text
            finally:
                self.active -= 1

    recalled = []
    for index in range(3):
        asset = _asset(conf="L3")
        version = _version(asset)
        item = _recalled(asset, version)
        item.matched_chunks[0]["content"] = f"CHUNK_{index}"
        recalled.append(item)
        if index < 2:
            db_session.add_all([asset, version])
            db_session.add(
                KnowledgeAssetChunk(
                    asset_id=asset.id,
                    version_id=version.id,
                    chunk_index=0,
                    chunk_type="governance_text",
                    content_text=f"PARENT_{index}",
                    chunk_status="active",
                )
            )
    await db_session.commit()
    scrubber = PipelineScrub()
    task = asyncio.create_task(
        retrieval.gather_parent_context(
            db_session, recalled, scrubber, trace_id="pipeline", parent_doc_limit=2
        )
    )
    try:
        await asyncio.wait_for(parent_started.wait(), timeout=1)
        # A synchronization assertion, not an elapsed-latency promise: parent 0
        # is still explicitly blocked when the independent fallback must start.
        await asyncio.wait_for(fallback_started.wait(), timeout=1)
        assert not release_parent.is_set() and not task.done()
    finally:
        release_parent.set()
        result = await task
    assert scrubber.active == 0 and scrubber.peak == 2
    assert [e.asset.id for e in result] == [r.asset.id for r in recalled]
    assert [e.snippet for e in result] == ["SAFE_PARENT_0", "SAFE_PARENT_1", "SAFE_CHUNK_2"]


@pytest.mark.parametrize("failed_parents", [set(), {0}, {0, 2}, {0, 1, 2}])
@pytest.mark.parametrize("parent_positions", [(0, 1, 2), (1, 4, 8)])
async def test_pipeline_preserves_original_fallback_quota_and_order(
    db_session, failed_parents, parent_positions
):
    failed_positions = {parent_positions[i] for i in failed_parents}
    all_original = parent_positions == (0, 1, 2)
    recalled = []
    for index in range(10):
        asset = _asset(conf="L3")
        version = _version(asset)
        item = _recalled(asset, version, original_allowed=all_original or index in parent_positions)
        asset.summaries = [
            KnowledgeAssetSummary(
                version_id=version.id,
                summary_type="redacted_summary",
                content=f"SAFE_SUMMARY_{index}",
            )
        ]
        item.matched_chunks[0]["content"] = f"CHUNK_{index}"
        recalled.append(item)
        if index in parent_positions:
            db_session.add_all([asset, version])
            db_session.add(
                KnowledgeAssetChunk(
                    asset_id=asset.id,
                    version_id=version.id,
                    chunk_index=0,
                    chunk_type="governance_text",
                    content_text=f"PARENT_{index}",
                    chunk_status="active",
                )
            )
    await db_session.commit()

    class SelectiveScrub:
        chunks = []

        async def scrub(self, text, **kwargs):
            kind, index = text.split("_")
            if kind == "PARENT" and int(index) in failed_positions:
                return None
            if kind == "CHUNK":
                self.chunks.append(int(index))
            return "SAFE_" + text

    scrubber = SelectiveScrub()
    result = await retrieval.gather_parent_context(
        db_session, recalled, scrubber, trace_id="quota", parent_doc_limit=3
    )
    covered = set(parent_positions) - failed_positions
    expected_fallback = [i for i in range(10) if i not in covered][:6]
    assert sorted(scrubber.chunks) == [
        i for i in expected_fallback if all_original or i in failed_positions
    ]
    expected = sorted(covered | set(expected_fallback))
    assert [e.asset.id for e in result] == [recalled[i].asset.id for i in expected]
    assert [e.snippet for e in result] == [
        f"SAFE_PARENT_{i}"
        if i in covered
        else f"SAFE_CHUNK_{i}"
        if all_original or i in failed_positions
        else f"SAFE_SUMMARY_{i}"
        for i in expected
    ]


async def test_pipeline_keeps_two_successful_chunks_and_never_relays_failed_scrubs(db_session):
    asset = _asset(conf="L4")
    version = _version(asset)
    item = _recalled(asset, version)
    item.matched_chunks = [
        {
            "knowledge_id": version.weknora_doc_id,
            "chunk_index": i,
            "seq": i,
            "content": f"RAW_{i}",
        }
        for i in range(4)
    ]
    db_session.add_all([asset, version])
    db_session.add(
        KnowledgeAssetChunk(
            asset_id=asset.id,
            version_id=version.id,
            chunk_index=0,
            chunk_type="governance_text",
            content_text="PARENT_FAIL",
            chunk_status="active",
        )
    )
    await db_session.commit()

    class FailedThenSafe:
        calls = []

        async def scrub(self, text, **kwargs):
            self.calls.append(text)
            return None if text in {"PARENT_FAIL", "RAW_0"} else "SAFE_" + text[-1]

    scrubber = FailedThenSafe()
    result = await retrieval.gather_parent_context(db_session, [item], scrubber, trace_id="safe")
    assert scrubber.calls == ["PARENT_FAIL", "RAW_0", "RAW_1", "RAW_2"]
    assert [e.snippet for e in result] == ["SAFE_1", "SAFE_2"]
    assert [e.seq for e in result] == [1, 2]


@pytest.mark.parametrize("failure", ["cancel", "error"])
async def test_pipeline_cleans_both_phases_and_dependency_waiters(db_session, failure):
    fallback_started = asyncio.Event()
    fail_now = asyncio.Event()

    class BlockingPipeline:
        active = 0
        peak = 0

        async def scrub(self, text, **kwargs):
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                if text == "PARENT_1":
                    return "SAFE_PARENT_1"
                if text == "CHUNK_2":
                    fallback_started.set()
                    await fail_now.wait()
                    raise RuntimeError("controlled_failure")
                await asyncio.Event().wait()
            finally:
                self.active -= 1

    recalled = []
    for index in range(9):
        asset = _asset(conf="L3")
        version = _version(asset)
        item = _recalled(asset, version)
        item.matched_chunks[0]["content"] = f"CHUNK_{index}"
        recalled.append(item)
        if index < 2:
            db_session.add_all([asset, version])
            db_session.add(
                KnowledgeAssetChunk(
                    asset_id=asset.id,
                    version_id=version.id,
                    chunk_index=0,
                    chunk_type="governance_text",
                    content_text=f"PARENT_{index}",
                    chunk_status="active",
                )
            )
    await db_session.commit()
    scrubber = BlockingPipeline()
    task = asyncio.create_task(
        retrieval.gather_parent_context(
            db_session, recalled, scrubber, trace_id="cleanup-pipeline", parent_doc_limit=2
        )
    )
    try:
        await asyncio.wait_for(fallback_started.wait(), timeout=1)
        if failure == "cancel":
            task.cancel()
        else:
            fail_now.set()
        with pytest.raises(asyncio.CancelledError if failure == "cancel" else RuntimeError):
            await asyncio.wait_for(task, timeout=1)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert scrubber.active == 0 and scrubber.peak == 2


@pytest.mark.parametrize("failure", ["cancel", "error"])
async def test_evidence_cleans_up_running_and_queued_workers(failure, caplog):
    caplog.set_level(logging.INFO, logger="app.services.retrieval")
    started_two = asyncio.Event()
    fail_now = asyncio.Event()

    class BlockingScrub:
        active = 0

        async def scrub(self, text, **kwargs):
            self.active += 1
            if self.active == 2:
                started_two.set()
            try:
                if text == "RAW_0":
                    await fail_now.wait()
                    raise RuntimeError("controlled_failure")
                await asyncio.Event().wait()
            finally:
                self.active -= 1

    recalled = []
    for index in range(3):
        asset = _asset(conf="L4")
        item = _recalled(asset, _version(asset))
        item.matched_chunks[0]["content"] = f"RAW_{index}"
        recalled.append(item)
    scrubber = BlockingScrub()
    task = asyncio.create_task(retrieval.gather_evidence(recalled, scrubber, trace_id="cleanup"))
    try:
        await asyncio.wait_for(started_two.wait(), timeout=1)
        if failure == "cancel":
            task.cancel()
        else:
            fail_now.set()
        with pytest.raises(asyncio.CancelledError if failure == "cancel" else RuntimeError):
            await asyncio.wait_for(task, timeout=1)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert scrubber.active == 0
    stage = next(r for r in caplog.records if r.message == "retrieval_evidence_stage")
    assert stage.evidence_stage == "fallback_chunks"
    assert stage.stage_status == ("cancelled" if failure == "cancel" else "error")
    assert stage.job_count == 3
    assert stage.started_job_count >= 2 and stage.completed_job_count == 0
    assert stage.evidence_count == 0 and stage.duration_ms >= 0
    scrub_records = [r for r in caplog.records if r.message == "retrieval_evidence_scrub"]
    assert len(scrub_records) == stage.started_job_count
    assert any(r.scrub_status == "cancelled" for r in scrub_records)
    if failure == "error":
        assert any(r.scrub_status == "error" for r in scrub_records)
    for record in [stage, *scrub_records]:
        assert "RAW_" not in repr(record.__dict__)
        assert "controlled_failure" not in repr(record.__dict__)


def test_join_parent_document_rebuilds_page_markers():
    chunks = [
        KnowledgeAssetChunk(
            asset_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            chunk_index=0,
            chunk_type="governance_text",
            content_text="第一章 摘要",
            source_page=1,
            source_section="第一章 摘要",
            chunk_status="active",
        ),
        KnowledgeAssetChunk(
            asset_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            chunk_index=1,
            chunk_type="governance_text",
            content_text="第二页正文内容",
            source_page=2,
            chunk_status="active",
        ),
    ]
    joined = retrieval._join_parent_document(chunks)
    assert "[第 1 页]" in joined
    assert "[第 2 页]" in joined
    assert joined.index("[第 1 页]") < joined.index("第一章 摘要")
    assert joined.index("[第 2 页]") < joined.index("第二页正文内容")


async def test_gather_parent_context_returns_full_text(db_session):
    asset = _asset()
    version = _version(asset)
    db_session.add(asset)
    db_session.add(version)
    db_session.add(
        KnowledgeAssetChunk(
            asset_id=asset.id,
            version_id=version.id,
            chunk_index=0,
            chunk_type="governance_text",
            content_text="第一章 需求分析",
            source_page=1,
            source_section="第一章 需求分析",
            chunk_status="active",
        )
    )
    db_session.add(
        KnowledgeAssetChunk(
            asset_id=asset.id,
            version_id=version.id,
            chunk_index=1,
            chunk_type="governance_text",
            content_text="第二章 实施方案",
            source_page=2,
            source_section="第二章 实施方案",
            chunk_status="active",
        )
    )
    await db_session.commit()

    desens = FakeDesens()
    evidences = await retrieval.gather_parent_context(
        db_session,
        [_recalled(asset, version)],
        desens,
        trace_id="trc-parent",
    )
    assert len(evidences) == 1
    ev = evidences[0]
    assert ev.used_layer == "original"
    assert ev.seq is None  # 文件级证据
    assert ev.asset.id == asset.id
    assert "第一章 需求分析" in ev.snippet
    assert "第二章 实施方案" in ev.snippet
    assert "[第 2 页]" in ev.snippet
    # L1/L2 直通，不触发 LLM 擦洗。
    assert desens.calls == []


async def test_gather_parent_context_scrubs_high_confidentiality(db_session):
    asset = _asset(conf="L3")
    version = _version(asset)
    db_session.add(asset)
    db_session.add(version)
    db_session.add(
        KnowledgeAssetChunk(
            asset_id=asset.id,
            version_id=version.id,
            chunk_index=0,
            chunk_type="governance_text",
            content_text="L3 敏感方案全文",
            source_page=1,
            chunk_status="active",
        )
    )
    await db_session.commit()

    desens = FakeDesens(result="擦洗后的安全全文")
    evidences = await retrieval.gather_parent_context(
        db_session,
        [_recalled(asset, version)],
        desens,
        trace_id="trc-parent",
    )
    assert desens.calls, "L3 全文必须走 LLM 擦洗"
    assert len(evidences) == 1
    assert "擦洗后的安全全文" in evidences[0].snippet
    assert "L3 敏感方案全文" not in evidences[0].snippet


@pytest.mark.parametrize("timeout", [False, True])
async def test_long_parent_plan_preserves_full_text_or_uses_safe_chunk_fallback(
    db_session, monkeypatch, timeout
):
    import json

    from app.services import desensitization

    asset = _asset(conf="L3")
    version = _version(asset)
    source = "PRIVATE客户甲\n" + "原文流程。\n" * 2000 + "完整结尾。"
    db_session.add_all([asset, version])
    db_session.add(
        KnowledgeAssetChunk(
            asset_id=asset.id,
            version_id=version.id,
            chunk_index=0,
            chunk_type="governance_text",
            content_text=source,
            chunk_status="active",
        )
    )
    await db_session.commit()
    finished = asyncio.Event()

    class Model:
        async def chat_completion(self, messages, **kwargs):
            if kwargs.get("json_object"):
                assert json.loads(messages[1]["content"])["text"] == source
                if timeout:
                    try:
                        await asyncio.Event().wait()
                    finally:
                        finished.set()
                return json.dumps(
                    {
                        "complete": True,
                        "redactions": [{"text": "PRIVATE客户甲", "replacement": "【客户】"}],
                    }
                )
            return "安全命中片段"

    monkeypatch.setattr(desensitization, "_LONG_SCRUB_TIMEOUT_SECONDS", 0.001 if timeout else 8)
    evidence = await retrieval.gather_parent_context(
        db_session,
        [_recalled(asset, version)],
        desensitization.LlmOutputDesensitizer(Model()),
        trace_id="long-parent",
        parent_doc_char_limit=40000,
    )
    assert len(evidence) == 1
    if timeout:
        assert finished.is_set()
        assert evidence[0].snippet == "安全命中片段"
    else:
        assert evidence[0].snippet == source.replace("PRIVATE客户甲", "【客户】")
    assert "PRIVATE" not in evidence[0].snippet


async def test_gather_parent_context_scrub_failure_downgrades(db_session):
    asset = _asset(conf="L5")
    version = _version(asset)
    db_session.add(asset)
    db_session.add(version)
    db_session.add(
        KnowledgeAssetChunk(
            asset_id=asset.id,
            version_id=version.id,
            chunk_index=0,
            chunk_type="governance_text",
            content_text="L5 原文",
            source_page=1,
            chunk_status="active",
        )
    )
    await db_session.commit()

    # 擦洗不可用 → 该篇不进父上下文（conservative），无摘要则最终无证据。
    desens = FakeDesens(result=None)
    evidences = await retrieval.gather_parent_context(
        db_session,
        [_recalled(asset, version)],
        desens,
        trace_id="trc-parent",
    )
    assert evidences == []


async def test_gather_parent_context_no_chunks_falls_back(db_session):
    """存量资产（阶段3 部署前无 chunk 注册表）回退命中片段，问答不因阶段4变空。"""
    asset = _asset()
    version = _version(asset)
    db_session.add(asset)
    db_session.add(version)
    await db_session.commit()

    desens = FakeDesens()
    evidences = await retrieval.gather_parent_context(
        db_session,
        [_recalled(asset, version)],
        desens,
        trace_id="trc-parent",
    )
    assert len(evidences) == 1
    assert "命中片段内容" in evidences[0].snippet
    assert evidences[0].seq == 0  # 回退仍为片段级证据


async def test_gather_parent_context_respects_doc_limit(db_session):
    assets = [_asset(title=f"资产{i}") for i in range(3)]
    recalled = []
    for asset in assets:
        version = _version(asset)
        db_session.add(asset)
        db_session.add(version)
        db_session.add(
            KnowledgeAssetChunk(
                asset_id=asset.id,
                version_id=version.id,
                chunk_index=0,
                chunk_type="governance_text",
                content_text=f"全文内容-{asset.title}",
                source_page=1,
                chunk_status="active",
            )
        )
        recalled.append(_recalled(asset, version))
    await db_session.commit()

    desens = FakeDesens()
    evidences = await retrieval.gather_parent_context(
        db_session,
        recalled,
        desens,
        trace_id="trc-parent",
        parent_doc_limit=1,
    )
    # 只有第一篇走全文；其余资产有 chunk 但超 N，仍回退片段证据。
    full_texts = [e for e in evidences if e.seq is None]
    assert len(full_texts) == 1
    assert "全文内容-资产0" in full_texts[0].snippet
    assert len(evidences) == 3  # 每资产至少一条（全文或兜底片段）


async def test_gather_parent_context_truncates_head(db_session):
    asset = _asset()
    version = _version(asset)
    db_session.add(asset)
    db_session.add(version)
    db_session.add(
        KnowledgeAssetChunk(
            asset_id=asset.id,
            version_id=version.id,
            chunk_index=0,
            chunk_type="governance_text",
            content_text="A" * 300,
            source_page=1,
            chunk_status="active",
        )
    )
    await db_session.commit()

    desens = FakeDesens()
    evidences = await retrieval.gather_parent_context(
        db_session,
        [_recalled(asset, version)],
        desens,
        trace_id="trc-parent",
        parent_doc_char_limit=100,
    )
    assert len(evidences) == 1
    assert "[内容过长已截断" in evidences[0].snippet
    assert len(evidences[0].snippet) < 300


async def test_gather_parent_context_no_original_permission_summary_fallback(db_session):
    asset = _asset()
    version = _version(asset)
    asset.summaries = [
        KnowledgeAssetSummary(
            asset_id=asset.id,
            version_id=version.id,
            summary_type="detailed",
            content="安全业务摘要",
        )
    ]
    db_session.add(asset)
    db_session.add(version)
    await db_session.commit()

    desens = FakeDesens()
    evidences = await retrieval.gather_parent_context(
        db_session,
        [_recalled(asset, version, original_allowed=False)],
        desens,
        trace_id="trc-parent",
    )
    assert len(evidences) == 1
    assert evidences[0].used_layer == "summary"
    assert "安全业务摘要" in evidences[0].snippet


async def test_synthesize_answer_uses_full_text_blocks():
    asset = _asset(title="实施方案")
    llm = CaptureLLM()
    evidence = retrieval.Evidence(
        asset=asset,
        used_layer="original",
        snippet="第一章 全文内容",
        seq=None,
        weknora_chunk_ref=None,
    )
    answer = await retrieval.synthesize_answer(
        llm, "方案要点是什么", [evidence], trace_id="trc-synth"
    )
    assert answer == "【答案】"
    assert llm.messages is not None
    user_content = llm.messages[1]["content"]
    assert "《实施方案》" in user_content
    assert "保密 L1" in user_content
    assert "第一章 全文内容" in user_content
    assert "交叉综合" in llm.messages[0]["content"]

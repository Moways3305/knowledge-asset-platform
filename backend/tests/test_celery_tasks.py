"""Celery 异步治理作业测试（直接调用 job service，不需真实 Redis/worker）。

覆盖：
- 上传建 processing 任务 + 入队；作业完成后落 ai_result + pending_confirmation。
- 作业幂等：重跑不重复建 ai_result / 不重复终态审计。
- 处理失败递增 retry_count、尊重 max_retries，只留安全失败元数据。
- WeKnora 解析对账更新 pending/processing，单条失败不中断整批。
- 归档扫描产生 warning/candidate 事件 + 通知，且**不**置 archived；重复扫描去重。
- 复用扫描更新 last_called_at，并对合格资产恰好产生一条升格推荐；重复扫描去重。
- 无 source_file_ref / storage_ref / weknora id / 原始抽取文本 泄露。
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timedelta, timezone

from PIL import Image
from sqlalchemy import func, select

from app.models.agent import (
    AgentCall,
    AgentCallCitation,
    AgentGatewayDecision,
    AgentGatewayDecisionItem,
)
from app.models.audit import AuditEvent
from app.models.indexing_job import OpsReconcileHeartbeat
from app.models.ingest import IngestTask, IngestTaskAiResult
from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetVersion,
)
from app.models.lifecycle import AssetLifecycleEvent, NotificationRecord
from app.seed.dev_seed import (
    KA_PROJECT_ALPHA,
    PROJECT_ALPHA,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
)
from app.services.desensitization import NullDesensitizer
from app.services.extraction import ExtractionPage, ExtractionResult
from app.services.jobs import ingest_processing, lifecycle_scan, parse_reconcile, reuse_upgrade
from app.services.llm_client import NullLLMClient
from app.services.ocr import OCRError, OCRPageResult, OCRResult
from app.services.storage import LocalFileStorage
from app.services.weknora_client import WeKnoraError

UPLOAD = "/api/v1/ingest/upload"
_TXT = "异步处理测试\n第一行标题\n正文内容若干段。".encode()


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


def _now():
    return datetime.now(timezone.utc)


# ---------------- 异步入库：processing → 作业 → pending_confirmation ----------------
async def test_upload_processing_then_job_persists(client, db_session, monkeypatch):
    import app.services.ingest as ingest_mod

    recorded = {}

    async def fake_enqueue(session, task_id, *, storage, llm, desensitizer, trace_id):
        recorded["task_id"] = task_id
        return "processing"  # 模拟非 eager：排队，保持 processing

    monkeypatch.setattr(ingest_mod, "enqueue_ingest_processing", fake_enqueue)

    resp = await client.post(
        UPLOAD, headers=_hdr(USER_CONSULTANT), files={"file": ("doc.txt", _TXT, "text/plain")}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "processing"
    task_id = uuid.UUID(resp.json()["ingest_task_id"])
    assert recorded["task_id"] == task_id

    # ai-result 在作业完成前安全表示为 processing。
    ai = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    assert ai.json()["content_processing_status"] == "processing"

    # 直接跑作业（用同一受控存储读字节）。
    status = await ingest_processing.process_upload_task(
        db_session,
        task_id,
        storage=client._kap_storage,
        llm=client._kap_generation_llm,
        desensitizer=NullDesensitizer(),
        trace_id="trc-celery",
    )
    assert status == "pending_confirmation"
    ai2 = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    body = ai2.json()
    assert body["suggested_title"]
    assert body["status"] == "pending_confirmation"
    # 无内部引用泄露。
    for tok in ("source_file_ref", "storage_ref", "kb_id", "doc_id", "sk-"):
        assert tok not in ai2.text


async def test_processing_job_idempotent(client, db_session, monkeypatch):
    import app.services.ingest as ingest_mod

    async def fake_enqueue(session, task_id, *, storage, llm, desensitizer, trace_id):
        return "processing"

    monkeypatch.setattr(ingest_mod, "enqueue_ingest_processing", fake_enqueue)
    resp = await client.post(
        UPLOAD, headers=_hdr(USER_CONSULTANT), files={"file": ("a.txt", _TXT, "text/plain")}
    )
    task_id = uuid.UUID(resp.json()["ingest_task_id"])

    kw = dict(
        storage=client._kap_storage,
        llm=client._kap_generation_llm,
        desensitizer=NullDesensitizer(),
        trace_id="trc-idem",
    )
    s1 = await ingest_processing.process_upload_task(db_session, task_id, **kw)
    s2 = await ingest_processing.process_upload_task(db_session, task_id, **kw)
    assert s1 == s2 == "pending_confirmation"
    # 重跑不重复建 ai_result。
    cnt = await db_session.scalar(
        select(func.count())
        .select_from(IngestTaskAiResult)
        .where(IngestTaskAiResult.ingest_task_id == task_id)
    )
    assert cnt == 1
    # 不重复终态审计（ingest.ai_extracted 仅一条）。
    audits = await db_session.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.action == "ingest.ai_extracted")
        .where(AuditEvent.target_id == task_id)
    )
    assert audits == 1


async def test_ocr_failure_persists_mixed_pdf_page_plan_for_exact_retry(
    client, db_session, monkeypatch
):
    ref = client._kap_storage.save(b"fake-pdf", original_name="mixed.pdf")
    task = IngestTask(
        source="path_b_upload",
        source_file_ref=ref,
        source_file_name="mixed.pdf",
        source_file_mime_type="application/pdf",
        source_file_hash="mixed-hash",
        status="processing",
        created_by=USER_CONSULTANT,
    )
    db_session.add(task)
    await db_session.commit()
    mixed = ExtractionResult(
        text="{{page:1}}\nnative first\n{{page:3}}\nnative third",
        status="ocr_required",
        error_type=None,
        error_message=None,
        char_count=50,
        pages=(
            ExtractionPage(1, "native first", "extracted"),
            ExtractionPage(2, "", "ocr_required"),
            ExtractionPage(3, "native third", "extracted"),
        ),
        source_kind="pdf",
    )
    monkeypatch.setattr(ingest_processing, "extract_text", lambda *_args, **_kwargs: mixed)
    calls = 0
    retried_extraction = None

    def fake_recognize(_content, extraction):
        nonlocal calls, retried_extraction
        calls += 1
        if calls == 1:
            raise OCRError("ocr_timeout", "OCR 服务暂不可用。")
        retried_extraction = extraction
        return OCRResult(
            text="{{page:1}}\nnative first\n{{page:2}}\nrecognized second\n{{page:3}}\nnative third",
            status="succeeded",
            confidence=91,
            pages=(
                OCRPageResult(1, "native first", "skipped_text", None),
                OCRPageResult(2, "recognized second", "succeeded", 91),
                OCRPageResult(3, "native third", "skipped_text", None),
            ),
        )

    monkeypatch.setattr(ingest_processing.ocr, "recognize", fake_recognize)
    kwargs = {
        "storage": client._kap_storage,
        "llm": client._kap_generation_llm,
        "desensitizer": NullDesensitizer(),
        "trace_id": "mixed-ocr-retry",
    }

    assert await ingest_processing.process_upload_task(db_session, task.id, **kwargs) == "failed"
    ai = await db_session.scalar(
        select(IngestTaskAiResult).where(IngestTaskAiResult.ingest_task_id == task.id)
    )
    assert [item["source_status"] for item in ai.ocr_page_results] == [
        "extracted",
        "ocr_required",
        "extracted",
    ]
    assert [item["status"] for item in ai.ocr_page_results] == [
        "skipped_text",
        "pending",
        "skipped_text",
    ]
    task.status = "processing"
    task.processing_stage = "ocr_queued"
    task.error_type = None
    task.error_message = None
    await db_session.commit()

    assert (
        await ingest_processing.process_upload_task(db_session, task.id, **kwargs)
        == "pending_confirmation"
    )
    assert retried_extraction is not None
    assert [(page.page_number, page.status, page.text) for page in retried_extraction.pages] == [
        (1, "extracted", "native first"),
        (2, "ocr_required", ""),
        (3, "extracted", "native third"),
    ]


async def test_ocr_retry_keeps_image_route_when_mime_is_generic(client, db_session, monkeypatch):
    image = io.BytesIO()
    Image.new("RGB", (2, 2), "white").save(image, format="PNG")
    ref = client._kap_storage.save(image.getvalue(), original_name="scan.PNG")
    task = IngestTask(
        source="path_b_upload",
        source_file_ref=ref,
        source_file_name="scan.PNG",
        source_file_mime_type="application/octet-stream",
        source_file_hash="image-hash",
        status="processing",
        created_by=USER_CONSULTANT,
    )
    db_session.add(task)
    await db_session.commit()
    source_kinds = []

    def fake_recognize(_content, extraction):
        source_kinds.append(extraction.source_kind)
        if len(source_kinds) == 1:
            raise OCRError("ocr_timeout", "OCR 服务暂不可用。")
        return OCRResult(
            text="{{page:1}}\nrecognized image",
            status="succeeded",
            confidence=90,
            pages=(OCRPageResult(1, "recognized image", "succeeded", 90),),
        )

    monkeypatch.setattr(ingest_processing.ocr, "recognize", fake_recognize)
    kwargs = {
        "storage": client._kap_storage,
        "llm": client._kap_generation_llm,
        "desensitizer": NullDesensitizer(),
        "trace_id": "image-ocr-retry",
    }
    assert await ingest_processing.process_upload_task(db_session, task.id, **kwargs) == "failed"
    task.status = "processing"
    task.processing_stage = "ocr_queued"
    task.error_type = None
    task.error_message = None
    await db_session.commit()

    retried_status = await ingest_processing.process_upload_task(db_session, task.id, **kwargs)
    assert (retried_status, source_kinds) == ("pending_confirmation", ["image", "image"])
    assert source_kinds == ["image", "image"]


async def test_processing_failure_retry_then_failed(db_session, tmp_path):
    storage = LocalFileStorage(tmp_path / "store")
    ref = storage.save(b"some bytes", original_name="x.txt")
    task = IngestTask(
        source="path_b_upload",
        source_file_ref=ref,
        source_file_name="x.txt",
        source_file_mime_type="text/plain",
        source_file_size=10,
        source_file_hash="h",
        status="processing",
        created_by=USER_CONSULTANT,
        max_retries=2,
    )
    db_session.add(task)
    await db_session.commit()
    # 删除文件 → 作业读盘抛错（瞬时失败）。
    storage.resolve_path(ref).unlink()

    kw = dict(
        storage=storage, llm=NullLLMClient(), desensitizer=NullDesensitizer(), trace_id="trc-fail"
    )
    s1 = await ingest_processing.process_upload_task(db_session, task.id, **kw)
    assert s1 == "processing" and task.retry_count == 1
    s2 = await ingest_processing.process_upload_task(db_session, task.id, **kw)
    assert s2 == "failed" and task.retry_count == 2  # 达到 max_retries → failed
    # 终态后不再处理。
    s3 = await ingest_processing.process_upload_task(db_session, task.id, **kw)
    assert s3 == "failed" and task.retry_count == 2
    # 未建 ai_result；失败信息安全（无内部引用）。
    cnt = await db_session.scalar(
        select(func.count())
        .select_from(IngestTaskAiResult)
        .where(IngestTaskAiResult.ingest_task_id == task.id)
    )
    assert cnt == 0
    assert "store" not in (task.error_message or "")
    assert ref not in (task.error_message or "")


async def test_content_terminal_failure_is_idempotent(db_session, tmp_path):
    storage = LocalFileStorage(tmp_path / "store2")
    # 仅空白的 .txt → 抽取 status=empty → 内容性终态 failed（不耗尽重试）。
    ref = storage.save(b"   \n  \t  ", original_name="blank.txt")
    task = IngestTask(
        source="path_b_upload",
        source_file_ref=ref,
        source_file_name="blank.txt",
        source_file_mime_type="text/plain",
        source_file_size=9,
        source_file_hash="hblank",
        status="processing",
        created_by=USER_CONSULTANT,
        max_retries=3,
    )
    db_session.add(task)
    await db_session.commit()

    kw = dict(
        storage=storage, llm=NullLLMClient(), desensitizer=NullDesensitizer(), trace_id="trc-term"
    )
    s1 = await ingest_processing.process_upload_task(db_session, task.id, **kw)
    assert s1 == "failed"
    assert task.retry_count == 0  # 内容性终态，非瞬时重试
    # 重跑：已处理（有 ai_result）→ 幂等跳过。
    s2 = await ingest_processing.process_upload_task(db_session, task.id, **kw)
    assert s2 == "failed"
    assert task.retry_count == 0  # 第二次不递增

    # 至多一行 ai_result。
    ai_cnt = await db_session.scalar(
        select(func.count())
        .select_from(IngestTaskAiResult)
        .where(IngestTaskAiResult.ingest_task_id == task.id)
    )
    assert ai_cnt == 1
    # 恰好一条终态 ingest.failed 审计（不因重跑重复）。
    failed_cnt = await db_session.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.action == "ingest.failed")
        .where(AuditEvent.target_id == task.id)
    )
    assert failed_cnt == 1
    # 失败信息 / 审计不含内部引用 / 绝对路径。
    assert "store2" not in (task.error_message or "")
    assert ref not in (task.error_message or "")
    audit_row = (
        await db_session.execute(
            select(AuditEvent)
            .where(AuditEvent.action == "ingest.failed")
            .where(AuditEvent.target_id == task.id)
        )
    ).scalar_one()
    extra_text = str(audit_row.extra or {})
    assert (
        "store2" not in extra_text and ref not in extra_text and "source_file_ref" not in extra_text
    )


# ---------------- WeKnora 解析对账 ----------------
class FakeParseWeKnora:
    def __init__(self, statuses, fail_ids=()):
        self.statuses = statuses  # doc_id -> parse_status
        self.fail_ids = set(fail_ids)

    async def get_knowledge(self, knowledge_id, *, trace_id=None):
        if knowledge_id in self.fail_ids:
            raise WeKnoraError("weknora_down", "底座不可用")
        return {"id": knowledge_id, "parse_status": self.statuses.get(knowledge_id, "processing")}


async def _new_version(db_session, *, doc_id, parse_status):
    asset = KnowledgeAsset(
        title=f"异步资产 {doc_id}",
        scope="company",
        zone="material",
        asset_type="methodology",
        owner_user_id=USER_CONSULTANT,
        maintainer_user_id=USER_CONSULTANT,
        visibility="public",
        confidentiality_level="L2",
        ai_access_level="A1",
        asset_status="active",
    )
    version = KnowledgeAssetVersion(
        asset_id=asset.id,
        version_no="v1",
        version_status="active",
        created_by=USER_CONSULTANT,
        weknora_kb_id="wk-kb-company",
        weknora_doc_id=doc_id,
        weknora_parse_status=parse_status,
    )
    asset.versions.append(version)
    asset.current_version_id = version.id
    db_session.add(asset)
    await db_session.commit()
    return version


async def test_parse_reconcile_updates_and_tolerates_failure(db_session, monkeypatch):
    monkeypatch.setattr(parse_reconcile, "weknora_enabled", lambda: True)
    v1 = await _new_version(db_session, doc_id="r5-doc-1", parse_status="processing")
    v2 = await _new_version(db_session, doc_id="r5-doc-2", parse_status="processing")
    fake = FakeParseWeKnora({"r5-doc-1": "completed"}, fail_ids={"r5-doc-2"})
    res = await parse_reconcile.reconcile_parse_statuses(db_session, fake, trace_id="trc-parse")
    assert res["updated"] == 1 and res["failed"] == 1
    await db_session.refresh(v1)
    await db_session.refresh(v2)
    assert v1.weknora_parse_status == "completed"
    assert v2.weknora_parse_status == "processing"  # 失败项不变，整批未中断
    # 对账心跳已落库（供运维页展示对账健康）。
    hb = (
        await db_session.execute(
            select(OpsReconcileHeartbeat)
            .order_by(OpsReconcileHeartbeat.observed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    assert hb is not None
    assert hb.processed == 1 and hb.updated == 1 and hb.failed == 1


async def test_parse_reconcile_requires_age_and_consecutive_failure_evidence(
    db_session, monkeypatch
):
    monkeypatch.setattr(parse_reconcile, "weknora_enabled", lambda: True)
    version = await _new_version(db_session, doc_id="r5-interrupted-doc", parse_status="processing")
    version.index_status = "indexing"
    version.created_at = _now() - timedelta(minutes=31)
    await db_session.commit()
    fake = FakeParseWeKnora({}, fail_ids={"r5-interrupted-doc"})

    first = await parse_reconcile.reconcile_parse_statuses(db_session, fake, trace_id="first")
    await db_session.refresh(version)
    assert first["interrupted"] == 0
    assert version.index_status == "indexing"
    assert version.index_reconcile_failure_count == 1

    second = await parse_reconcile.reconcile_parse_statuses(db_session, fake, trace_id="second")
    await db_session.refresh(version)
    assert second["interrupted"] == 1
    assert version.index_status == "index_failed"
    assert version.index_error_code == "index_interrupted"
    assert "中断" in (version.index_error_message or "")
    audit = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.action == "knowledge.index_interrupted_detected",
                AuditEvent.target_id == version.id,
            )
        )
    ).scalar_one()
    assert audit.before_snapshot == {"index_status": "indexing"}
    assert audit.after_snapshot == {
        "index_status": "index_failed",
        "reason_code": "index_interrupted",
    }


async def test_parse_reconcile_confirmed_processing_never_becomes_interrupted(
    db_session, monkeypatch
):
    monkeypatch.setattr(parse_reconcile, "weknora_enabled", lambda: True)
    version = await _new_version(db_session, doc_id="r5-live-doc", parse_status="processing")
    version.index_status = "indexing"
    version.created_at = _now() - timedelta(hours=2)
    version.index_reconcile_failure_count = 8
    await db_session.commit()

    result = await parse_reconcile.reconcile_parse_statuses(
        db_session,
        FakeParseWeKnora({"r5-live-doc": "processing"}),
        trace_id="live",
    )
    await db_session.refresh(version)
    assert result["interrupted"] == 0
    assert version.index_status == "indexing"
    assert version.index_reconcile_failure_count == 0


async def test_parse_reconcile_restores_interrupted_item_when_processing_is_queryable(
    db_session, monkeypatch
):
    monkeypatch.setattr(parse_reconcile, "weknora_enabled", lambda: True)
    version = await _new_version(
        db_session, doc_id="r5-recovered-interruption", parse_status="pending"
    )
    version.index_status = "index_failed"
    version.index_error_code = "index_interrupted"
    version.index_error_message = "索引处理中断，等待恢复"
    version.index_reconcile_failure_count = 2
    version.index_last_reconcile_failed_at = _now()
    await db_session.commit()

    result = await parse_reconcile.reconcile_parse_statuses(
        db_session,
        FakeParseWeKnora({"r5-recovered-interruption": "processing"}),
        trace_id="interruption-recovered",
    )
    await db_session.refresh(version)

    assert result["interrupted_recovered"] == 1
    assert result["updated"] == 1
    assert version.index_status == "indexing"
    assert version.weknora_parse_status == "processing"
    assert version.index_error_code is None
    assert version.index_error_message is None
    assert version.index_reconcile_failure_count == 0
    assert version.index_last_reconcile_failed_at is None
    audit = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.action == "knowledge.index_interrupted_recovered",
                AuditEvent.target_id == version.id,
            )
        )
    ).scalar_one()
    assert audit.before_snapshot == {
        "index_status": "index_failed",
        "reason_code": "index_interrupted",
    }
    assert audit.after_snapshot == {
        "index_status": "indexing",
        "parse_status": "processing",
    }


# ---------------- 生命周期归档扫描 ----------------
async def _insert_inactive_asset(db_session, *, title, last_called_days_ago):
    asset = KnowledgeAsset(
        title=title,
        scope="company",
        zone="asset",
        asset_type="methodology",
        owner_user_id=USER_CONSULTANT,
        maintainer_user_id=USER_CONSULTANT,
        visibility="public",
        confidentiality_level="L2",
        ai_access_level="A1",
        asset_status="active",
        last_called_at=_now() - timedelta(days=last_called_days_ago),
    )
    db_session.add(asset)
    await db_session.commit()
    return asset


async def test_archive_scan_warns_without_archiving_and_dedup(db_session):
    asset = await _insert_inactive_asset(
        db_session, title="长期未调用资产", last_called_days_ago=800
    )
    r1 = await lifecycle_scan.scan_archive_candidates(db_session, trace_id="trc-arch", now=_now())
    assert r1["warnings"] >= 1
    await db_session.refresh(asset)
    # 绝不自动归档。
    assert asset.asset_status == "active"
    # 产生 archive_warning 事件 + 本地通知。
    warn_cnt = await db_session.scalar(
        select(func.count())
        .select_from(AssetLifecycleEvent)
        .where(AssetLifecycleEvent.asset_id == asset.id)
        .where(AssetLifecycleEvent.event_type == "archive_warning")
    )
    assert warn_cnt == 1
    notif = await db_session.scalar(
        select(func.count())
        .select_from(NotificationRecord)
        .where(NotificationRecord.recipient_user_id == USER_CONSULTANT)
    )
    assert notif >= 1
    # 重复扫描去重：不再新增 warning。
    await lifecycle_scan.scan_archive_candidates(db_session, trace_id="trc-arch", now=_now())
    warn_cnt2 = await db_session.scalar(
        select(func.count())
        .select_from(AssetLifecycleEvent)
        .where(AssetLifecycleEvent.asset_id == asset.id)
        .where(AssetLifecycleEvent.event_type == "archive_warning")
    )
    assert warn_cnt2 == 1


async def test_archive_scan_promotes_to_candidate_after_warning_period(db_session):
    asset = await _insert_inactive_asset(
        db_session, title="预警期已过资产", last_called_days_ago=800
    )
    # 预置一条 40 天前的 archive_warning（预警期 30 天已过）。
    old_warning = AssetLifecycleEvent(
        asset_id=asset.id,
        event_type="archive_warning",
        old_status="active",
        triggered_by="system",
        reason="历史预警",
        trace_id="seed",
        created_at=_now() - timedelta(days=40),
    )
    db_session.add(old_warning)
    await db_session.commit()

    r = await lifecycle_scan.scan_archive_candidates(db_session, trace_id="trc-cand", now=_now())
    assert r["candidates"] == 1
    cand_cnt = await db_session.scalar(
        select(func.count())
        .select_from(AssetLifecycleEvent)
        .where(AssetLifecycleEvent.asset_id == asset.id)
        .where(AssetLifecycleEvent.event_type == "archive_candidate")
    )
    assert cand_cnt == 1
    await db_session.refresh(asset)
    assert asset.asset_status == "active"  # 仍不自动归档
    # 再扫一次去重。
    r2 = await lifecycle_scan.scan_archive_candidates(db_session, trace_id="trc-cand", now=_now())
    assert r2["candidates"] == 0


# ---------------- 跨项目复用 / 升格推荐 ----------------
async def _cite_asset(db_session, *, asset_id, project_id):
    call = AgentCall(
        caller_user_id=USER_CONSULTANT,
        project_id=project_id,
        query_text="q",
        model_key="m",
        provider="weknora_llm",
        capability="qa",
        call_status="allowed",
        trace_id="t",
    )
    db_session.add(call)
    await db_session.flush()
    decision = AgentGatewayDecision(
        call_id=call.id,
        caller_user_id=USER_CONSULTANT,
        decision_status="allowed",
    )
    db_session.add(decision)
    await db_session.flush()
    item = AgentGatewayDecisionItem(
        decision_id=decision.id,
        call_id=call.id,
        caller_user_id=USER_CONSULTANT,
        target_asset_id=asset_id,
        target_scope="project",
        target_confidentiality_level="L2",
        target_ai_access_level="A1",
        discovery_allowed=True,
        summary_allowed=True,
        original_allowed=True,
        returned_layer="original",
    )
    db_session.add(item)
    await db_session.flush()
    db_session.add(
        AgentCallCitation(
            call_id=call.id,
            decision_item_id=item.id,
            cited_asset_id=asset_id,
            used_access_layer="original",
            cited_zone="asset",
            citation_order=1,
        )
    )
    await db_session.commit()


async def test_reuse_scan_updates_usage_and_recommends_once(db_session):
    await _cite_asset(db_session, asset_id=KA_PROJECT_ALPHA, project_id=PROJECT_ALPHA)
    # min_calls=1 让单次引用即合格（验证推荐+去重路径）。
    r1 = await reuse_upgrade.scan_reuse_and_recommend(db_session, trace_id="trc-reuse", min_calls=1)
    assert r1["usage_updated"] >= 1
    assert r1["recommended"] == 1
    asset = await db_session.get(KnowledgeAsset, KA_PROJECT_ALPHA)
    assert asset.last_called_at is not None
    # 审计恰好一条升格推荐事件。
    rec_cnt = await db_session.scalar(
        select(func.count())
        .select_from(AuditEvent)
        .where(AuditEvent.action == "knowledge.upgrade_recommended")
        .where(AuditEvent.target_id == KA_PROJECT_ALPHA)
    )
    assert rec_cnt == 1
    # 通知发给 Boss / 咨询总监。
    gov_notif = await db_session.scalar(
        select(func.count())
        .select_from(NotificationRecord)
        .where(NotificationRecord.recipient_user_id.in_([USER_BOSS, USER_DIRECTOR]))
    )
    assert gov_notif >= 1
    # 资产 scope 未被自动升格。
    assert asset.scope == "project"
    # 重复扫描去重：不再新增推荐。
    r2 = await reuse_upgrade.scan_reuse_and_recommend(db_session, trace_id="trc-reuse", min_calls=1)
    assert r2["recommended"] == 0

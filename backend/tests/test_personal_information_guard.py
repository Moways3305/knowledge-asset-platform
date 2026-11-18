"""Synthetic canaries must never escape through inspection evidence or derived outputs."""

import json
import logging

import pytest
from sqlalchemy import select
from test_maintenance_agent import configure, content_asset, headers, run_asset
from test_maintenance_batches import Segments, finish

from app.core.logging import JsonFormatter
from app.core.personal_information import personal_information_matches, redact_personal_information
from app.db.utils import utc_now
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetChunk, KnowledgeAssetSummary
from app.models.maintenance_agent import MaintenanceIssue, MaintenanceIssueEvent, MaintenanceRunItem
from app.schemas.knowledge import SummaryOut
from app.schemas.maintenance_agent import ScanSettings
from app.schemas.notification import BusinessNotificationOut
from app.services.llm_client import NullLLMClient
from app.services.maintenance_rules import analyze

PHONE = "13800000000"
EMAIL = "privacy-canary@example.invalid"


@pytest.mark.parametrize(
    "source,secret",
    [
        (f"联系方式 {PHONE}", PHONE),
        ("电话：+86 138-0000-0000", "138-0000-0000"),
        ("电话：１３８００００００００", "１３８００００００００"),
        ("电话：138\u200b00000000", "138\u200b00000000"),
        (f"邮箱 {EMAIL}", EMAIL),
        ("姓名：测试甲", "测试甲"),
        ("家庭住址：虚构测试市样例路999号", "虚构测试市样例路999号"),
        ("诊断结果：虚构健康测试值", "虚构健康测试值"),
        ("护照号码：TEST98765", "TEST98765"),
        ("指纹模板：SYNTHETIC-BIOMETRIC", "SYNTHETIC-BIOMETRIC"),
    ],
)
def test_recognition_returns_locations_without_values(source, secret):
    hits = personal_information_matches(source)
    assert hits
    assert secret not in repr(hits)
    assert secret not in redact_personal_information(source)
    masked = redact_personal_information(source, preserve_offsets=True)
    assert len(masked) == len(source)
    assert secret not in masked


def test_redacted_placeholders_are_not_new_findings():
    assert not personal_information_matches("姓名：【联系人】 电话：【手机号】 正文普通流程")
    assert not personal_information_matches("/knowledge/00000000-0000-0000-0000-000000000001")


def test_summary_and_notification_projection_filter_historical_values():
    from app.services.knowledge_projection import _select_summary_text

    source = f"姓名：测试甲，邮箱 {EMAIL}，电话 {PHONE}"
    summary = SummaryOut(one_liner=source, detailed=source, key_points=[source]).model_dump_json()
    item = BusinessNotificationOut(
        id="00000000-0000-0000-0000-000000000001",
        event_type="test",
        category="knowledge",
        title=source,
        summary=source,
        object_name=source,
        project_name=source,
        created_at=utc_now(),
        is_read=False,
        read_at=None,
        task_status="failed",
        task_group="attention",
        action_required=True,
        next_action_label=source,
        failure_reason=source,
        recovery_suggestion=source,
        target={"route_key": "knowledge", "resource_id": "00000000-0000-0000-0000-000000000001"},
    ).model_dump_json()
    for token in (PHONE, EMAIL, "测试甲"):
        assert token not in summary + item
    # Redact before a fallback preview truncates an identifier into an unrecognizable suffix.
    preview = _select_summary_text("L3", {"safe_summary": "正文" * 98 + PHONE})
    assert "1380" not in preview


def test_logging_sanitizes_message_args_nested_fields_and_exceptions():
    record = logging.LogRecord(
        "privacy.test", logging.ERROR, __file__, 1, "phone=%s email=%s", (PHONE, EMAIL), None
    )
    record.details = {
        "raw_response": f"任意业务正文 {PHONE}",
        "phone": PHONE,
        "nested": [{"message": EMAIL}],
    }
    record.asset_id = "00000000-0000-0000-0000-000000000001"
    record.trace_id = "f7fecffa-6e13-4123-8567-891122334455".replace("-", "")
    output = JsonFormatter().format(record)
    assert PHONE not in output and EMAIL not in output and "任意业务正文" not in output
    assert record.asset_id in output
    assert record.trace_id in output


def test_sanitizer_failure_hides_text_and_field_context_is_not_bypassed(monkeypatch):
    from app.core import personal_information as privacy

    source = "家庭住址：【说明】虚构测试市样例路999号"
    assert "虚构测试市" not in privacy.redact_personal_information(source)

    def unavailable(_):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(privacy, "personal_information_matches", unavailable)
    assert PHONE not in privacy.redact_personal_information(PHONE)


@pytest.mark.parametrize("kind", ["business", "ops"])
async def test_external_notification_delivery_filters_legacy_values(db_session, kind):
    from test_notification_delivery import Sender, dispatch, model, seed

    (row_id,) = await seed(db_session, kind)
    row = await db_session.get(model(kind), row_id)
    row.title = f"测试提醒 电话 {PHONE}"
    if kind == "business":
        row.summary = f"邮箱 {EMAIL}"
    else:
        row.content = f"邮箱 {EMAIL}"
    await db_session.commit()
    sender = Sender()
    await dispatch(db_session, kind, sender)
    assert sender.calls
    sent = json.dumps(sender.calls)
    assert PHONE not in sent and EMAIL not in sent


def test_audit_write_and_historical_projection_share_personal_redaction():
    from app.services.audit import _sanitize

    payload = {
        "reason": f"联系 {PHONE} 邮箱 {EMAIL}",
        "家庭住址": "虚构住址",
        "phoneNumber": PHONE,
        "asset_id": "00000000-0000-0000-0000-000000000001",
    }
    safe = _sanitize(payload)
    assert PHONE not in json.dumps(safe) and EMAIL not in json.dumps(safe)
    assert "家庭住址" not in safe and "phoneNumber" not in safe
    assert safe["asset_id"] == payload["asset_id"]


async def test_quality_model_never_receives_personal_identifiers():
    class Model:
        async def chat_completion(self, messages, **kwargs):
            sent = json.dumps(messages, ensure_ascii=False)
            assert PHONE not in sent and EMAIL not in sent
            body = json.loads(messages[-1]["content"])["document"]
            return json.dumps(
                {"complete": True, "findings": [{"rule": "summary_mismatch", "quote": body}]}
            )

    findings, reason = await analyze(
        {"body": f"联系电话：{PHONE}", "summary": f"邮箱：{EMAIL}"}, ScanSettings(), Model()
    )
    assert reason is None and findings
    assert PHONE not in json.dumps(findings)


@pytest.mark.parametrize("boundary_secret", [PHONE, EMAIL])
@pytest.mark.parametrize("summary_type", ["redacted_one_liner", "key_points"])
async def test_whole_document_privacy_runs_without_model_and_closes_after_fix(
    client, sessionmaker_fixture, tmp_path, boundary_secret, summary_type
):
    maker = sessionmaker_fixture
    await configure(client, content=True)
    # First identifier straddles a batch boundary; second is beyond the old 5000-character limit.
    body = "正文" * 2998 + boundary_secret + "正文" * 3500 + "\n" + EMAIL
    asset_id, storage = await content_asset(maker, tmp_path, body=body)
    async with maker() as session:
        asset = await session.get(KnowledgeAsset, asset_id)
        session.add(
            KnowledgeAssetSummary(
                asset_id=asset_id,
                version_id=asset.current_version_id,
                summary_type=summary_type,
                content=f"摘要电话 {PHONE}",
            )
        )
        await session.commit()
    run_id = await run_asset(maker, asset_id)
    await finish(maker, NullLLMClient(), storage)
    root = "/api/v1/maintenance-agent"
    report = (await client.get(f"{root}/policies/company/runs/{run_id}", headers=headers())).json()
    assert report["items"][0]["coverage"]["privacy"] == "complete", report
    assert report["items"][0]["coverage"]["quality"] == "model_configuration_error"
    issues = (
        await client.get(f"{root}/issues?asset_id={asset_id}&category=privacy", headers=headers())
    ).json()
    assert issues["total"] == 1
    issue_id = issues["items"][0]["id"]
    detail = (await client.get(f"{root}/issues/{issue_id}", headers=headers())).json()
    assert detail["evidence"]["counts"] == {
        "phone": 2 if boundary_secret == PHONE else 1,
        "email": 1 if boundary_secret == PHONE else 2,
    }, detail
    assert any(loc.get("summary_type") == summary_type for loc in detail["evidence"]["locations"])
    async with maker() as session:
        stored = (
            await session.scalars(
                select(MaintenanceIssue).where(MaintenanceIssue.asset_id == asset_id)
            )
        ).all()
        items = (
            await session.scalars(
                select(MaintenanceRunItem).where(MaintenanceRunItem.run_id == run_id)
            )
        ).all()
        persisted = json.dumps([i.evidence for i in stored] + [i.work_state for i in items])
        assert PHONE not in persisted and EMAIL not in persisted
        chunks = (
            await session.scalars(
                select(KnowledgeAssetChunk).where(KnowledgeAssetChunk.asset_id == asset_id)
            )
        ).all()
        for chunk in chunks:
            chunk.content_text = "普通正文，已完成处理。"
            chunk.chunk_hash = "fixed"
        summaries = (
            await session.scalars(
                select(KnowledgeAssetSummary).where(KnowledgeAssetSummary.asset_id == asset_id)
            )
        ).all()
        for summary in summaries:
            summary.content = "普通摘要，已完成处理。"
        asset = await session.get(KnowledgeAsset, asset_id)
        asset.updated_at = utc_now()
        await session.commit()
    await run_asset(maker, asset_id, kind="recheck")
    await finish(maker, NullLLMClient(), storage)
    detail = (await client.get(f"{root}/issues/{issue_id}", headers=headers())).json()
    assert detail["status"] == "resolved"


async def test_old_evidence_and_user_reasons_redacted(client, sessionmaker_fixture, tmp_path):
    maker = sessionmaker_fixture
    await configure(client, content=True)
    asset_id, storage = await content_asset(maker, tmp_path, body=f"联系电话：{PHONE}")
    await run_asset(maker, asset_id)
    await finish(maker, Segments(), storage)
    async with maker() as session:
        issue = await session.scalar(
            select(MaintenanceIssue).where(
                MaintenanceIssue.asset_id == asset_id,
                MaintenanceIssue.rule == "personal_information",
            )
        )
        issue.evidence = {"quote": f"电话 {PHONE} 邮箱 {EMAIL}"}
        session.add(
            MaintenanceIssueEvent(issue_id=issue.id, action="in_progress", reason=f"联系 {PHONE}")
        )
        issue_id = issue.id
        await session.commit()
    response = await client.get(f"/api/v1/maintenance-agent/issues/{issue_id}", headers=headers())
    assert response.status_code == 200
    assert PHONE not in response.text and EMAIL not in response.text


async def test_body_without_authorization_is_not_marked_privacy_complete(
    client, sessionmaker_fixture, tmp_path
):
    await configure(client, content=False)
    asset_id, storage = await content_asset(sessionmaker_fixture, tmp_path, body=PHONE)
    run_id = await run_asset(sessionmaker_fixture, asset_id)
    model = Segments()
    await finish(sessionmaker_fixture, model, storage)
    report = (
        await client.get(
            f"/api/v1/maintenance-agent/policies/company/runs/{run_id}", headers=headers()
        )
    ).json()
    assert report["items"][0]["coverage"]["privacy"] == "content_not_authorized"
    assert not model.documents
    issues = (
        await client.get(
            f"/api/v1/maintenance-agent/issues?asset_id={asset_id}&category=privacy",
            headers=headers(),
        )
    ).json()
    assert issues["total"] == 0

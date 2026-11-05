"""KAP HTTP Markdown intake, confirmation, and reviewed project publication.

Only project/member fixture setup writes SQL. Assets, versions, tasks, reviews,
and indexes under test must be created by the normal API and worker code.
"""

import asyncio
import hashlib
import json
from pathlib import Path
import secrets
import time
import uuid
from urllib.parse import urlsplit


def fixture_document(marker):
    return (
        "# 虚构月舟设备检修规程\n\n"
        "本文仅用于隔离升级验收，不含真实客户或生产资料。\n"
        "月舟设备的例行检修间隔为23天，每次检修由三名工程师共同完成。\n"
        "检修前应登记设备状态并核对备件清单，检修中逐项检查，检修后记录结果。\n"
        "培训采用示例设备进行，负责人检查记录完整性后安排下一轮检修。\n"
        "验收人员依据本规程核对检修间隔和工程师人数，不引入其他设备的参数。\n"
        "原文件核对码：" + marker + "。\n"
    ).encode()


def relative_preview_url(value):
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/api/v1/preview/"):
        raise RuntimeError("preview URL must remain inside the isolated KAP service")
    return value


async def request(check, name, client, method, path, *, expected=200, **kwargs):
    response = await client.request(method, path, **kwargs)
    if response.status_code != expected:
        # Body may contain sensitive values: keep it private, never in check facts.
        evidence = Path("/evidence/kap-upload-response-private.json")
        evidence.write_text(
            json.dumps({"case": name, "status": response.status_code, "body": response.text})
        )
        evidence.chmod(0o600)
    check(name, response.status_code == expected, http_status=response.status_code)
    return response


async def prepare_project(users):
    from app.db.session import get_sessionmaker
    from app.models.identity import Project, ProjectMember
    from app.services.naming_rules import _ensure_initial_revisions

    project = uuid.uuid4()
    async with get_sessionmaker()() as session:
        await _ensure_initial_revisions(session)
        session.add(
            Project(
                id=project,
                name="虚构月舟发布项目",
                status="active",
                project_code="KAPFIX",
                project_code_active=True,
            )
        )
        await session.flush()
        for role, project_role in (("consultant", "consultant"), ("boss", "project_manager")):
            session.add(
                ProjectMember(
                    project_id=project,
                    user_id=users[role]["id"],
                    project_role=project_role,
                    status="active",
                )
            )
        await session.commit()
    return str(project)


async def version_snapshot(asset_id):
    """Read-only corroboration; never repair data or mark an index as successful."""
    from sqlalchemy import select
    from app.db.session import get_sessionmaker
    from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion

    async with get_sessionmaker()() as session:
        asset = await session.get(KnowledgeAsset, uuid.UUID(asset_id))
        version = await session.get(KnowledgeAssetVersion, asset.current_version_id)
        count = len(
            (
                await session.scalars(
                    select(KnowledgeAsset.id).where(KnowledgeAsset.source_asset_id == asset.id)
                )
            ).all()
        )
        return {
            "scope": asset.scope,
            "project_id": str(asset.project_id) if asset.project_id else None,
            "source_asset_id": str(asset.source_asset_id) if asset.source_asset_id else None,
            "version_id": str(version.id),
            "canonical_name": asset.canonical_name,
            "directory_key": version.directory_key,
            "naming_rule_version": version.naming_rule_version,
            "kb": version.weknora_kb_id,
            "doc": version.weknora_doc_id,
            "derivatives": count,
        }


async def wait_for_processing(check, client, task_id):
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        response = await client.get(f"/api/v1/ingest/{task_id}/status")
        if response.status_code != 200:
            check("kap_upload_progress_readable", False, http_status=response.status_code)
        body = response.json()
        stage = body.get("stage")
        if stage == "awaiting_confirmation":
            check("kap_upload_worker_processed", True)
            return
        if body.get("status") in {"failed", "cancelled", "degraded"} or stage in {
            "waiting_generation_config",
            "content_generation_failed",
            "ocr_failed",
        }:
            check("kap_upload_worker_processed", False)
        await asyncio.sleep(2)
    check("kap_upload_processing_deadline", False)


async def wait_for_index(check, client, asset_id, label):
    # Dispatch the normal reconciliation task through the broker. No direct SQL
    # state changes, dependency override, fake completion, or worker eager mode.
    from app.worker.celery_app import celery_app
    from app.services.error_catalog import safe_code

    deadline = time.monotonic() + 600
    next_reconcile = 0
    while time.monotonic() < deadline:
        response = await client.get("/api/v1/knowledge/" + asset_id)
        if response.status_code != 200:
            check(
                "kap_upload_asset_readable", False, fixture=label, http_status=response.status_code
            )
        body = response.json()
        if body.get("index_status") == "indexed" and body.get("weknora_parse_status") in {
            "completed",
            "duplicate",
        }:
            check("kap_upload_index_completed", True, fixture=label)
            return body
        if body.get("index_status") in {"index_failed", "skipped"}:
            check(
                "kap_upload_index_completed",
                False,
                fixture=label,
                error_code=safe_code(body.get("index_error_code")),
            )
        if time.monotonic() >= next_reconcile:
            celery_app.send_task("weknora.parse_reconcile")
            next_reconcile = time.monotonic() + 10
        await asyncio.sleep(2)
    check("kap_upload_index_deadline", False, fixture=label)


async def preview(check, http, asset_id, content, label):
    response = await request(
        check, "kap_upload_preview_issued", http, "POST", f"/api/v1/knowledge/{asset_id}/preview"
    )
    entry = await request(
        check,
        "kap_upload_preview_entry",
        http,
        "GET",
        relative_preview_url(response.json()["preview_entry_url"]),
    )
    check("kap_upload_preview_kind", entry.json().get("render_type") == "markdown", fixture=label)
    file = await request(
        check,
        "kap_upload_original_file",
        http,
        "GET",
        relative_preview_url(entry.json()["file_url"]),
    )
    check(
        "kap_upload_original_bytes_preserved",
        hashlib.sha256(file.content).digest() == hashlib.sha256(content).digest(),
        fixture=label,
    )


async def run(clients, users, check):
    from app.db.session import get_engine

    consultant, boss, admin = (clients[r] for r in ("consultant", "boss", "admin"))
    project = await prepare_project(users)
    marker = "KAPUPLOAD" + secrets.token_hex(8).upper()
    content = fixture_document(marker)
    filename = "synthetic-maintenance-v1.md"
    files = {"file": (filename, content, "text/markdown")}
    await request(
        check,
        "kap_admin_upload_denied",
        admin,
        "POST",
        "/api/v1/ingest/upload",
        expected=403,
        files=files,
    )
    upload = await request(
        check,
        "kap_upload_accepted",
        consultant,
        "POST",
        "/api/v1/ingest/upload",
        files=files,
        data={"target_scope": "personal"},
    )
    task_id = upload.json()["ingest_task_id"]
    check("kap_upload_async_dispatch", upload.json().get("status") == "processing")
    await wait_for_processing(check, consultant, task_id)
    ai = await request(
        check, "kap_upload_ai_result", consultant, "GET", f"/api/v1/ingest/{task_id}/ai-result"
    )
    advice = ai.json()
    check(
        "kap_upload_real_content_generation",
        advice.get("suggestion_generation_status") == "generated"
        and advice.get("content_processing_status") == "llm"
        and bool(advice.get("suggested_summary")),
    )
    check("kap_upload_text_extracted", marker in (advice.get("extracted_text_preview") or ""))
    metadata = await request(
        check, "kap_upload_admin_metadata", admin, "GET", f"/api/v1/ingest/{task_id}/ai-result"
    )
    check(
        "kap_upload_admin_content_hidden",
        marker not in metadata.text
        and metadata.json().get("extracted_text_preview") is None
        and metadata.json().get("suggested_summary") is None,
    )

    confirmation = {
        "title": "虚构月舟设备检修规程",
        "one_liner": "虚构月舟检修规范",
        "summary": "虚构月舟设备检修的流程说明。",
        "key_points": ["按规定周期检修"],
        "tags": ["虚构验收"],
        "target_scope": "personal",
        "target_zone": "material",
        "confidentiality_level": "L2",
        "directory_key": "personal.learning_notes",
    }
    confirmed = await request(
        check,
        "kap_upload_confirmed",
        consultant,
        "POST",
        f"/api/v1/ingest/{task_id}/confirm",
        json=confirmation,
    )
    source_id = confirmed.json()["result_asset_id"]
    check("kap_upload_asset_created", bool(source_id))
    source_detail = await wait_for_index(check, consultant, source_id, "personal")
    check(
        "kap_upload_canonical_markdown_generated",
        source_detail.get("canonical_markdown_status") == "generated",
    )
    await request(
        check,
        "kap_upload_repeat_confirmation_denied",
        consultant,
        "POST",
        f"/api/v1/ingest/{task_id}/confirm",
        expected=409,
        json=confirmation,
    )
    await request(
        check,
        "kap_upload_private_asset_hidden",
        boss,
        "GET",
        "/api/v1/knowledge/" + source_id,
        expected=404,
    )
    await preview(check, consultant, source_id, content, "personal")
    await request(
        check,
        "kap_upload_personal_asset_confirmed",
        consultant,
        "POST",
        f"/api/v1/my/knowledge/{source_id}/confirm-asset",
    )
    source_before = await version_snapshot(source_id)

    publication = {
        "target_project_id": project,
        "confidentiality_level": "L2",
        "naming": {
            "subject": "虚构月舟设备检修规程",
            "subject_is_manual": True,
            "formed_on": "2026-11-05",
            "version": "V1",
            "directory_key": "project.deliverables",
        },
    }
    proposed = await request(
        check,
        "kap_upload_publication_preview",
        consultant,
        "POST",
        f"/api/v1/my/knowledge/{source_id}/submit-to-project-preview",
        json=publication,
    )
    proposed_name = proposed.json().get("canonical_name")
    check(
        "kap_upload_governed_name_previewed",
        bool(proposed_name) and proposed_name.startswith("【KAPFIX-2026-"),
    )
    submitted = await request(
        check,
        "kap_upload_project_submitted",
        consultant,
        "POST",
        f"/api/v1/my/knowledge/{source_id}/submit-to-project",
        json=publication,
    )
    review_id = submitted.json()["review_task_id"]
    check("kap_upload_review_required", bool(review_id))
    await request(
        check,
        "kap_upload_submitter_cannot_approve",
        consultant,
        "POST",
        f"/api/v1/reviews/{review_id}/approve",
        expected=403,
        json={},
    )
    await request(
        check,
        "kap_upload_admin_cannot_approve",
        admin,
        "POST",
        f"/api/v1/reviews/{review_id}/approve",
        expected=403,
        json={},
    )
    approved = await request(
        check,
        "kap_upload_project_approved",
        boss,
        "POST",
        f"/api/v1/reviews/{review_id}/approve",
        json={},
    )
    target_id = approved.json()["target_asset_id"]
    check("kap_upload_independent_project_copy", bool(target_id) and target_id != source_id)
    detail = await wait_for_index(check, boss, target_id, "project")
    check(
        "kap_upload_published_metadata",
        detail.get("scope") == "project"
        and detail.get("project_id") == project
        and detail.get("directory_key") == "project.deliverables"
        and detail.get("canonical_name") == proposed_name,
    )
    await preview(check, boss, target_id, content, "project")
    await request(
        check,
        "kap_upload_admin_published_asset_hidden",
        admin,
        "GET",
        "/api/v1/knowledge/" + target_id,
        expected=404,
    )

    source_after, target = await version_snapshot(source_id), await version_snapshot(target_id)
    check(
        "kap_upload_source_unchanged",
        all(source_after[k] == v for k, v in source_before.items() if k != "derivatives")
        and source_after["derivatives"] == 1,
    )
    check(
        "kap_upload_published_lineage",
        target["source_asset_id"] == source_id
        and target["version_id"] != source_before["version_id"]
        and bool(target["naming_rule_version"])
        and bool(target["doc"])
        and target["doc"] != source_before["doc"]
        and target["kb"] != source_before["kb"],
    )
    repeated = await request(
        check,
        "kap_upload_repeat_publication",
        consultant,
        "POST",
        f"/api/v1/my/knowledge/{source_id}/submit-to-project",
        json=publication,
    )
    repeated_review = repeated.json()["review_task_id"]
    repeated_approval = await request(
        check,
        "kap_upload_repeat_approval",
        boss,
        "POST",
        f"/api/v1/reviews/{repeated_review}/approve",
        json={},
    )
    check(
        "kap_upload_publication_idempotent",
        repeated_approval.json()["target_asset_id"] == target_id
        and (await version_snapshot(source_id))["derivatives"] == 1,
    )
    from app.services.weknora_client import get_weknora_client

    weknora = get_weknora_client()
    for label, saved in (("personal", source_before), ("project", target)):
        chunks = await weknora.search(
            query=marker,
            kb_ids=[saved["kb"]],
            knowledge_ids=[saved["doc"]],
            keyword_only=True,
        )
        check(
            "kap_upload_foundation_content_verified",
            any(marker in c["content"] for c in chunks),
            fixture=label,
        )

    # Confirm original content through KAP's scope/authorization boundary, then QA.
    for scope, asset_id, http in (
        ("personal", source_id, consultant),
        ("project", target_id, boss),
    ):
        query = {
            "query": "月舟设备检修",
            "scope": scope,
            "intent": "search",
            "want_original": True,
            "asset_id": asset_id,
        }
        if scope == "project":
            query["filters"] = {"project_id": project}
        recalled = await request(
            check,
            "kap_upload_published_recall",
            http,
            "POST",
            "/api/v1/knowledge/search",
            json=query,
        )
        body = recalled.json()
        check(
            "kap_upload_published_original_available",
            body["original"]["available"]
            and marker in json.dumps(body["original"], ensure_ascii=False),
            fixture=scope,
        )
        for private in (
            source_before["kb"],
            source_before["doc"],
            target["kb"],
            target["doc"],
            "storage_ref",
            "api_key",
        ):
            check("kap_upload_recall_identifiers_hidden", private not in recalled.text)
    qa = await request(
        check,
        "kap_upload_project_qa",
        boss,
        "POST",
        "/api/v1/knowledge/search",
        json={
            "query": "月舟设备的检修间隔为多少天？",
            "scope": "project",
            "intent": "qa",
            "filters": {"project_id": project},
        },
    )
    body = qa.json()
    check(
        "kap_upload_project_answer_grounded",
        body.get("answer_status") == "answered"
        and "23" in (body.get("answer") or "")
        and bool(body.get("citations"))
        and all(c["asset_id"] == target_id for c in body["citations"]),
    )
    await get_engine().dispose()

"""入库流水线 API 测试（IMPLEMENT-05，Path B 最小闭环）。"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import delete

from app.models.weknora import WeknoraKbMapping
from app.seed.dev_seed import (
    PROJECT_ALPHA,
    PROJECT_BETA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_PROJECT_MANAGER,
)
from app.services.storage import LocalFileStorage, StorageError

UPLOAD = "/api/v1/ingest/upload"
KN = "/api/v1/knowledge"
MY = "/api/v1/my/knowledge"


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


_TXT_BYTES = (
    "零售数字化转型方案\n"
    "第一章 背景\n"
    "本文介绍零售企业数字化转型的五维度成熟度评估方法论与落地路径。"
).encode()

_MD_BYTES = (
    "# 项目复盘\n\n"
    "- 客户访谈纪要\n"
    "- 后续行动\n\n"
    "| 主题 | 结论 |\n"
    "| --- | --- |\n"
    "| 组织 | 需要统一节奏 |\n"
).encode()


async def _create_task(client, user_id, file_name="retail-strategy-v2.txt"):
    # Path B 现为真实文件上传 + 真实文本抽取；发送可抽取的真实文本字节。
    resp = await client.post(
        UPLOAD,
        headers=_hdr(user_id),
        files={"file": (file_name, _TXT_BYTES, "text/plain")},
    )
    return resp


def _confirm_payload(**over):
    base = {
        "title": "入库确认资产",
        "summary": "确认后的摘要内容",
        "tags": ["标签A", "标签B"],
        "target_scope": "personal",
        "target_zone": "material",
        "asset_type": "methodology",
        "confidentiality_level": "L2",
        "ai_access_level": "A2",
        "lifecycle_phase_key": "诊断",
    }
    base.update(over)
    return base


async def test_business_user_create_upload_no_internal_fields(client):
    """业务用户创建 upload 成功，响应不含内部字段 / 真实 URL。"""
    resp = await _create_task(client, USER_CONSULTANT)
    assert resp.status_code == 200
    body = resp.json()
    assert body["ingest_task_id"]
    assert body["status"] == "pending_confirmation"
    assert body["upload_url"] is None
    assert "source_file_ref" not in resp.text
    assert "storage_ref" not in resp.text


async def test_admin_create_upload_403(client):
    """纯 admin 创建 upload 返回 403 + admin_business_permission_denied。"""
    resp = await _create_task(client, USER_ADMIN_ONLY)
    assert resp.status_code == 403
    assert resp.json()["detail"]["denied_reason"] == "admin_business_permission_denied"


async def test_ai_result_no_internal_fields(client):
    """获取 AI 建议不泄露内部字段（source_file_ref / storage_ref）。"""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    resp = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    assert resp.status_code == 200
    assert resp.json()["suggested_title"]  # 创建人可见完整建议
    assert "source_file_ref" not in resp.text
    assert "storage_ref" not in resp.text


async def test_ai_result_admin_trimmed(client):
    """admin 看 AI 建议只得运营元数据，不返回业务建议正文。"""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    resp = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_ADMIN_ONLY))
    assert resp.status_code == 200
    body = resp.json()
    assert body["suggested_title"] is None
    assert body["suggested_summary"] is None
    assert body["confidence"] is not None  # 运营元数据仍可见


async def test_confirm_personal_then_visible_in_my_knowledge(client):
    """确认 personal 入库后，/my/knowledge 可看到新资产。"""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    resp = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_confirm_payload(title="我的入库个人资产", target_scope="personal"),
    )
    assert resp.status_code == 200
    asset_id = resp.json()["result_asset_id"]
    my = (await client.get(MY, headers=_hdr(USER_CONSULTANT))).json()
    assert any(i["id"] == asset_id for i in my["items"])


async def test_confirm_project_non_member_rejected_consultant_waits_for_review(client):
    """项目入库：非成员被拒；普通成员提交后等待审批且资产不可见。"""
    # 非成员项目 Beta（consultant 在 Beta 为 inactive）→ 403
    task1 = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    r1 = await client.post(
        f"/api/v1/ingest/{task1}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_confirm_payload(target_scope="project", target_project_id=str(PROJECT_BETA)),
    )
    assert r1.status_code == 403
    assert r1.json()["detail"]["denied_reason"] == "project_membership_required"

    # 成员项目 Alpha → 仅创建持久化审批任务，不创建可见资产。
    task2 = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    r2 = await client.post(
        f"/api/v1/ingest/{task2}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_confirm_payload(
            title="Alpha 入库项目资产",
            target_scope="project",
            target_project_id=str(PROJECT_ALPHA),
        ),
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "waiting_review"
    assert r2.json()["result_asset_id"] is None
    assert r2.json()["review_id"] is not None
    items = (await client.get(f"{KN}?scope=project", headers=_hdr(USER_CONSULTANT))).json()["items"]
    assert all(i["title"] != "Alpha 入库项目资产" for i in items)


async def test_project_manager_self_submission_is_confirmed_directly(client):
    """目标项目经理提交自己的项目知识，后端明确走经理自确认路径。"""
    task_id = (await _create_task(client, USER_PROJECT_MANAGER)).json()["ingest_task_id"]
    response = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_PROJECT_MANAGER),
        json=_confirm_payload(
            title="经理自确认项目资产",
            target_scope="project",
            target_project_id=str(PROJECT_ALPHA),
        ),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["result_asset_id"] is not None
    assert response.json()["review_id"] is None
    items = (await client.get(f"{KN}?scope=project", headers=_hdr(USER_PROJECT_MANAGER))).json()[
        "items"
    ]
    assert any(item["title"] == "经理自确认项目资产" for item in items)


async def test_consultant_company_confirm_rejected_boss_ok(client):
    """consultant 直接确认 company 资产被拒；boss 可确认。"""
    task1 = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    r1 = await client.post(
        f"/api/v1/ingest/{task1}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_confirm_payload(target_scope="company"),
    )
    assert r1.status_code == 403
    assert r1.json()["detail"]["denied_reason"] == "company_confirmation_requires_governance"

    task2 = (await _create_task(client, USER_BOSS)).json()["ingest_task_id"]
    r2 = await client.post(
        f"/api/v1/ingest/{task2}/confirm",
        headers=_hdr(USER_BOSS),
        json=_confirm_payload(title="公司级入库资产", target_scope="company"),
    )
    assert r2.status_code == 200


async def test_company_confirm_requires_ready_company_kb(client, db_session):
    await db_session.execute(delete(WeknoraKbMapping).where(WeknoraKbMapping.scope == "company"))
    await db_session.commit()
    task_id = (await _create_task(client, USER_BOSS)).json()["ingest_task_id"]
    response = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_BOSS),
        json=_confirm_payload(title="公司库未就绪", target_scope="company"),
    )
    assert response.status_code == 409
    assert response.json()["detail"]["denied_reason"] == "company_kb_not_ready"
    assert "wk-kb" not in response.text


async def test_confirm_l4_redacted_summary_no_key_points(client):
    """L4 confirm 后创建脱敏摘要；detail 不返回 key_points 敏感内容。"""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    r = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_confirm_payload(
            title="个人 L4 资产",
            target_scope="personal",
            confidentiality_level="L4",
            ai_access_level="A4",
        ),
    )
    asset_id = r.json()["result_asset_id"]
    detail = (await client.get(f"{KN}/{asset_id}", headers=_hdr(USER_CONSULTANT))).json()
    assert detail["summary"] is not None
    assert detail["summary"]["one_liner"].startswith("（脱敏）")
    assert detail["summary"]["key_points"] == []


async def test_second_confirm_returns_409(client):
    """二次 confirm 同一任务返回 409，不重复创建资产。"""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    p = _confirm_payload(target_scope="personal")
    r1 = await client.post(
        f"/api/v1/ingest/{task_id}/confirm", headers=_hdr(USER_CONSULTANT), json=p
    )
    assert r1.status_code == 200
    r2 = await client.post(
        f"/api/v1/ingest/{task_id}/confirm", headers=_hdr(USER_CONSULTANT), json=p
    )
    assert r2.status_code == 409
    assert r2.json()["detail"]["denied_reason"] == "ingest_already_confirmed"


async def test_confirm_by_other_non_governance_user_forbidden(client):
    """顾问 A 创建的任务，另一名非治理业务用户（经理 B）确认应被拒，且不创建资产。"""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    r = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_PROJECT_MANAGER),
        json=_confirm_payload(title="他人越权确认", target_scope="personal"),
    )
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "ingest_confirm_forbidden"
    # 经理 B 的个人知识列表不应出现该资产（未创建）。
    my = (await client.get(MY, headers=_hdr(USER_PROJECT_MANAGER))).json()
    assert all(i["title"] != "他人越权确认" for i in my["items"])


async def test_governance_can_confirm_others_task(client):
    """业务治理角色（boss）可确认他人创建的任务。"""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    r = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_BOSS),
        json=_confirm_payload(title="治理代确认资产", target_scope="company"),
    )
    assert r.status_code == 200


async def test_confirm_invalid_enum_returns_422(client):
    """非法 enum 值（保密级别 L9）返回 422，不创建资产。"""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    r = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_confirm_payload(target_scope="personal", confidentiality_level="L9"),
    )
    assert r.status_code == 422


async def test_confirm_visibility_persisted(client):
    """confirm 提交的 visibility 真实写入资产并在详情可见。"""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    r = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_confirm_payload(
            title="带可见性的资产", target_scope="personal", visibility="confidential"
        ),
    )
    asset_id = r.json()["result_asset_id"]
    detail = (await client.get(f"{KN}/{asset_id}", headers=_hdr(USER_CONSULTANT))).json()
    assert detail["visibility"] == "confidential"


async def test_upload_persists_real_file_and_no_leak(client):
    """上传真实文件：字节确实落盘到受控存储；响应不含存储引用 / 路径 / URL。"""
    resp = await client.post(
        UPLOAD,
        headers=_hdr(USER_CONSULTANT),
        files={"file": ("方案.pdf", b"hello-bytes-1234567890", "application/pdf")},
    )
    assert resp.status_code == 200
    text = resp.text
    # 响应只含安全元数据，绝不含内部引用 / 路径 / URL。
    for token in [
        "source_file_ref",
        "storage_ref",
        "internal://",
        "file://",
        "s3://",
        "oss://",
        "http://",
        "https://",
        str(client._kap_storage.root),
    ]:
        assert token not in text, f"响应不应泄露 {token}"

    # 存储目录中确实新增了一个非空文件（字节真的落盘）。
    files = [p for p in client._kap_storage.root.rglob("*") if p.is_file()]
    assert len(files) >= 1
    assert any(p.read_bytes() == b"hello-bytes-1234567890" for p in files)


async def test_upload_empty_file_rejected(client):
    """空文件被拒（422 empty_file），不创建任务、不落盘。"""
    resp = await client.post(
        UPLOAD,
        headers=_hdr(USER_CONSULTANT),
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["denied_reason"] == "empty_file"
    files = [p for p in client._kap_storage.root.rglob("*") if p.is_file()]
    assert files == []


async def test_upload_path_traversal_filename_normalized(client):
    """路径穿越文件名被归一化：不逃逸存储根目录，落盘文件名安全。"""
    resp = await client.post(
        UPLOAD,
        headers=_hdr(USER_CONSULTANT),
        files={"file": ("../../../etc/passwd", b"payload-bytes", "application/octet-stream")},
    )
    assert resp.status_code == 200
    root = client._kap_storage.root
    files = [p for p in root.rglob("*") if p.is_file()]
    assert len(files) == 1
    # 落盘路径仍在存储根目录下，且文件名不含路径分隔/穿越。
    assert str(files[0].resolve()).startswith(str(root))
    assert files[0].name == "etcpasswd" or "passwd" in files[0].name
    assert ".." not in files[0].name


async def test_admin_denied_upload_does_not_persist_file(client):
    """纯 admin 上传被拒（403），且不落盘任何字节。"""
    resp = await client.post(
        UPLOAD,
        headers=_hdr(USER_ADMIN_ONLY),
        files={"file": ("x.pdf", b"should-not-persist", "application/pdf")},
    )
    assert resp.status_code == 403
    files = [p for p in client._kap_storage.root.rglob("*") if p.is_file()]
    assert files == []


def test_storage_resolve_path_rejects_escape(tmp_path):
    """resolve_path 不能被路径穿越 / 兄弟前缀绕过到存储根之外。"""
    storage = LocalFileStorage(tmp_path / "root")
    # 同时创建一个共享前缀的兄弟目录，确保不是靠"不存在"才被拒。
    (tmp_path / "root2").mkdir(parents=True, exist_ok=True)
    (tmp_path / "root").mkdir(parents=True, exist_ok=True)

    # 路径穿越到兄弟目录（root2 与 root 共享字符串前缀）。
    with pytest.raises(StorageError):
        storage.resolve_path("internal://../root2/evil.pdf")
    # 直接穿越到上级。
    with pytest.raises(StorageError):
        storage.resolve_path("internal://../../etc/passwd")
    # 合法引用仍可解析，且落在 root 内。
    ok = storage.resolve_path("internal://abc123/file.pdf")
    assert ok.resolve().is_relative_to((tmp_path / "root").resolve())


def test_storage_save_stays_within_root(tmp_path):
    """save 的落盘路径始终在存储根之内，且文件名归一化无穿越。"""
    storage = LocalFileStorage(tmp_path / "root")
    ref = storage.save(b"bytes", original_name="../../../etc/passwd")
    path = storage.resolve_path(ref)
    assert path.resolve().is_relative_to((tmp_path / "root").resolve())
    assert ".." not in path.name


async def test_upload_extraction_success_content_based(client):
    """抽取成功：ai-result 含基于内容的建议 + 抽取预览（创建人完整视图）。"""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    r = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    assert r.status_code == 200
    body = r.json()
    assert body["extraction_status"] == "extracted"
    # 标题为平台规范命名（非"摘要式标题"/非抽取首行）。
    assert re.match(r"^【[^-】]+-[^】]+】.+_.+_\d{8}_V\d+_L[1-5]$", body["suggested_title"]), body[
        "suggested_title"
    ]
    # 抽取首行进入一句话摘要字段，不抢占标题。
    assert body["suggested_one_liner"] == "零售数字化转型方案"
    assert body["suggested_title"] != body["suggested_one_liner"]
    assert body["extracted_char_count"] > 0
    assert body["extracted_text_preview"] and "零售数字化转型" in body["extracted_text_preview"]


async def test_upload_markdown_enters_confirmation_with_extracted_text(client):
    """Markdown 上传走纯文本抽取成功路径，可进入资产化确认。"""
    resp = await client.post(
        UPLOAD,
        headers=_hdr(USER_CONSULTANT),
        files={"file": ("project-review.md", _MD_BYTES, "text/markdown")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending_confirmation"

    task_id = body["ingest_task_id"]
    ai = (
        await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    ).json()
    assert ai["status"] == "pending_confirmation"
    assert ai["extraction_status"] == "extracted"
    assert ai["extracted_char_count"] > 0
    assert ai["extracted_text_preview"] and "项目复盘" in ai["extracted_text_preview"]


async def test_upload_unsupported_still_pending(client):
    """不支持类型：标 unsupported，但任务仍待确认（不阻断人工补全）。"""
    resp = await client.post(
        UPLOAD,
        headers=_hdr(USER_CONSULTANT),
        files={"file": ("sheet.xlsx", b"PK\x03\x04binary-xlsx", "application/octet-stream")},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending_confirmation"
    task_id = resp.json()["ingest_task_id"]
    ai = (
        await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    ).json()
    assert ai["extraction_status"] == "unsupported"
    assert "人工补全" in ai["suggested_summary"]


async def test_upload_failed_extraction_persists_and_audits_no_leak(client):
    """损坏 PDF：状态 failed + 持久化错误 + ingest.failed 审计，且审计无抽取全文 / 内部引用。"""
    resp = await client.post(
        UPLOAD,
        headers={**_hdr(USER_CONSULTANT), "X-Trace-Id": "trc-extract-fail"},
        files={"file": ("broken.pdf", b"not a real pdf payload", "application/pdf")},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "failed"
    task_id = resp.json()["ingest_task_id"]
    ai = (
        await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    ).json()
    assert ai["extraction_status"] == "failed"
    assert ai["error_type"] == "extraction_failed"
    assert ai["error_message"]

    # 审计 trace（治理视图）含 ingest.failed，且不泄露抽取内容 / 内部引用。
    trace = await client.get("/api/v1/admin/audit/trace/trc-extract-fail", headers=_hdr(USER_BOSS))
    actions = {e["action"] for e in trace.json()["items"]}
    assert "ingest.failed" in actions
    for token in ["internal://", "source_file_ref", "storage_ref", "not a real pdf payload"]:
        assert token not in trace.text


async def test_admin_view_hides_extracted_fulltext(client):
    """admin 元数据视图不返回抽取全文 / 业务建议正文，但可见抽取状态。"""
    task_id = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    r = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_ADMIN_ONLY))
    assert r.status_code == 200
    body = r.json()
    assert body["suggested_title"] is None
    assert body["suggested_summary"] is None
    assert body["extracted_text_preview"] is None
    assert body["extraction_status"] == "extracted"  # 运营元数据仍可见
    assert "零售数字化转型" not in r.text  # 抽取全文不出现


async def test_duplicate_content_soft_hint_non_blocking(client):
    """相同内容哈希：第二次上传给非阻塞软提示，指向首个任务，不拦截。"""
    first = (await _create_task(client, USER_CONSULTANT)).json()["ingest_task_id"]
    second_resp = await _create_task(client, USER_CONSULTANT)
    assert second_resp.status_code == 200
    assert second_resp.json()["status"] == "pending_confirmation"  # 不阻断
    second = second_resp.json()["ingest_task_id"]
    ai = (
        await client.get(f"/api/v1/ingest/{second}/ai-result", headers=_hdr(USER_CONSULTANT))
    ).json()
    assert ai["is_possible_duplicate"] is True
    assert ai["duplicate_of_task_id"] == first


async def test_admin_ingest_list_operational_only(client):
    """admin 可看入库运营列表，不含 source_file_ref / storage_ref。"""
    await _create_task(client, USER_CONSULTANT)
    resp = await client.get("/api/v1/admin/ingest", headers=_hdr(USER_ADMIN_ONLY))
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1
    assert "source_file_ref" not in resp.text
    assert "storage_ref" not in resp.text

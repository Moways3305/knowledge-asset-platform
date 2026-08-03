"""Path A（企微微盘）待确认任务列表 + 确认链路复用测试。

验证：
- 业务用户只看到自己有权确认的 path_a_wecom 待确认任务；
- 非创建人用户看不到他人任务（包括治理角色），仅创建人本人可见；
- 纯 admin 不因系统身份获得业务查看 / 确认权（403）；
- 列表响应不泄露 source_file_ref / storage_ref / WeCom file_id / 下载 URL / token / WeKnora id；
- path_a_wecom 任务可走与 Path B 完全相同的 confirm 链路生成资产，确认后退出待确认列表；
- 重复确认已完成任务返回 409。
"""

from __future__ import annotations

from app.models.ingest import IngestTask, IngestTaskAiResult
from app.schemas.enums import IngestSource, IngestStatus
from app.seed.dev_seed import (
    PROJECT_ALPHA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_PROJECT_MANAGER,
)

PENDING = "/api/v1/ingest/pending"

# 故意放入"应被当作内部机密、绝不外泄"的引用，断言它们不出现在响应里。
SECRET_REF = "internal://secretbucket/aabbcc/zhanglue.pptx"
SECRET_WECOM_FILE_ID = "wecom_file_id_ABCDEF123456"


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


async def _make_path_a_task(
    session,
    *,
    created_by=USER_CONSULTANT,
    target_scope="personal",
    target_project_id=None,
    status=IngestStatus.pending_confirmation.value,
    file_name="零售渠道策略_V2.pptx",
    source=IngestSource.path_a_wecom.value,
):
    """直接插入一个 path_a_wecom 入库任务（模拟微盘扫描产物）+ AI 建议。"""
    task = IngestTask(
        source=source,
        # server-only 内部引用：包含一个假 WeCom file_id 以验证不外泄。
        source_file_ref=f"{SECRET_REF}?wecom_file_id={SECRET_WECOM_FILE_ID}",
        source_file_name=file_name,
        source_file_mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        source_file_size=2048,
        source_file_hash="deadbeef" * 8,
        status=status,
        target_scope=target_scope,
        target_project_id=target_project_id,
        target_zone="material",
        created_by=created_by,
    )
    task.ai_result = IngestTaskAiResult(
        suggested_title="【客户项目-交付成果】零售渠道策略_某客户_20260522_V2_L2",
        suggested_one_liner="零售渠道数字化策略第二版",
        suggested_summary="基于一阶段诊断结论细化线上线下渠道融合落地方案。",
        suggested_tags=["零售", "渠道策略"],
        suggested_asset_type="deliverable",
        suggested_confidentiality_level="L2",
        suggested_ai_access_level="A2",
        confidence=0.91,
        extraction_status="extracted",
        extracted_text="渠道融合的完整抽取正文，绝不应出现在待确认列表响应里。",
        naming_parsed_fields={"topic": "零售渠道策略", "date": "20260522"},
    )
    session.add(task)
    await session.commit()
    return task.id


async def test_business_user_sees_own_path_a_pending(client, db_session):
    """创建人（顾问）可在 Path A 列表看到自己的待确认任务，含安全建议元数据。"""
    task_id = await _make_path_a_task(db_session, created_by=USER_CONSULTANT)
    resp = await client.get(f"{PENDING}?source=path_a_wecom", headers=_hdr(USER_CONSULTANT))
    assert resp.status_code == 200
    body = resp.json()
    ids = [i["id"] for i in body["items"]]
    assert str(task_id) in ids
    item = next(i for i in body["items"] if i["id"] == str(task_id))
    assert item["source"] == "path_a_wecom"
    assert item["source_file_name"] == "零售渠道策略_V2.pptx"
    assert item["suggested_title"] == "零售渠道策略"
    assert item["target_scope"] == "personal"


async def test_other_user_cannot_see_others_task(client, db_session):
    """非创建人用户看不到他人任务（过滤，不泄露存在）。"""
    await _make_path_a_task(db_session, created_by=USER_CONSULTANT)
    resp = await client.get(f"{PENDING}?source=path_a_wecom", headers=_hdr(USER_PROJECT_MANAGER))
    assert resp.status_code == 200
    assert resp.json()["items"] == []


async def test_governance_sees_only_own_path_a_tasks(client, db_session):
    """治理角色（boss）也只能看到自己创建的待确认任务，不泄露他人任务。"""
    # boss 自己创建的任务应该可见。
    boss_task_id = await _make_path_a_task(db_session, created_by=USER_BOSS)
    # 别人的任务对 boss 不可见。
    other_task_id = await _make_path_a_task(db_session, created_by=USER_CONSULTANT)
    resp = await client.get(f"{PENDING}?source=path_a_wecom", headers=_hdr(USER_BOSS))
    assert resp.status_code == 200
    items = resp.json()["items"]
    ids = {str(i["id"]) for i in items}
    assert str(boss_task_id) in ids, "boss 应能看到自己创建的任务"
    assert str(other_task_id) not in ids, "boss 不应看到他人创建的待确认任务"


async def test_pure_admin_forbidden(client, db_session):
    """纯 admin 不是业务用户 → 403，不因系统身份获得业务查看 / 确认权。"""
    await _make_path_a_task(db_session, created_by=USER_CONSULTANT)
    resp = await client.get(f"{PENDING}?source=path_a_wecom", headers=_hdr(USER_ADMIN_ONLY))
    assert resp.status_code == 403
    assert resp.json()["detail"]["denied_reason"] == "admin_business_permission_denied"


async def test_pending_list_no_leak(client, db_session):
    """列表响应绝不泄露存储引用 / WeCom file_id / 下载 URL / token / 抽取全文。"""
    await _make_path_a_task(db_session, created_by=USER_CONSULTANT)
    resp = await client.get(f"{PENDING}?source=path_a_wecom", headers=_hdr(USER_CONSULTANT))
    assert resp.status_code == 200
    text = resp.text
    for token in [
        "source_file_ref",
        "storage_ref",
        SECRET_REF,
        SECRET_WECOM_FILE_ID,
        "wecom_file_id",
        "internal://",
        "file://",
        "http://",
        "https://",
        "cookie",
        "access_token",
        "kb_id",
        "weknora_doc_id",
        "渠道融合的完整抽取正文",  # 抽取全文不得出现
    ]:
        assert token not in text, f"待确认列表不应泄露 {token}"


async def test_source_filter_excludes_path_b(client, db_session):
    """?source=path_a_wecom 只返回 Path A 任务，不混入 Path B 上传任务。"""
    a_id = await _make_path_a_task(db_session, created_by=USER_CONSULTANT)
    b_id = await _make_path_a_task(
        db_session,
        created_by=USER_CONSULTANT,
        source=IngestSource.path_b_upload.value,
        file_name="本地上传.pptx",
    )
    resp = await client.get(f"{PENDING}?source=path_a_wecom", headers=_hdr(USER_CONSULTANT))
    ids = [i["id"] for i in resp.json()["items"]]
    assert str(a_id) in ids
    assert str(b_id) not in ids


async def test_path_a_task_confirmable_via_shared_chain(client, db_session):
    """path_a_wecom 任务可走与 Path B 相同的 confirm 链路生成资产，确认后退出待确认列表。"""
    task_id = await _make_path_a_task(
        db_session, created_by=USER_CONSULTANT, target_scope="personal"
    )
    # 复用 Path B 的 confirm 接口（同一 service，无 source 分叉）。
    confirm = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json={
            "title": "Path A 确认入库资产",
            "summary": "人工校正后的摘要内容",
            "tags": ["零售", "渠道"],
            "target_scope": "personal",
            "target_zone": "material",
            "confidentiality_level": "L2",
        },
    )
    assert confirm.status_code == 200, confirm.text
    asset_id = confirm.json()["result_asset_id"]
    assert asset_id

    # 入库后该任务退出 Path A 待确认列表（result_asset_id 已填）。
    after = await client.get(f"{PENDING}?source=path_a_wecom", headers=_hdr(USER_CONSULTANT))
    assert str(task_id) not in [i["id"] for i in after.json()["items"]]

    # 新资产出现在个人知识库。
    my = (await client.get("/api/v1/my/knowledge", headers=_hdr(USER_CONSULTANT))).json()
    assert any(i["id"] == asset_id for i in my["items"])


async def test_path_a_project_task_confirmable_by_member(client, db_session):
    """项目 Path A 任务可由项目有效成员（创建人）确认进项目资料区。"""
    task_id = await _make_path_a_task(
        db_session,
        created_by=USER_CONSULTANT,
        target_scope="project",
        target_project_id=PROJECT_ALPHA,
    )
    confirm = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json={
            "title": "Path A 项目资料",
            "summary": "项目过程材料摘要",
            "tags": ["渠道"],
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "target_zone": "material",
            "confidentiality_level": "L2",
        },
    )
    assert confirm.status_code == 200, confirm.text


async def test_second_confirm_returns_409(client, db_session):
    """已确认（completed）任务重复确认返回 409，不重复建资产。"""
    task_id = await _make_path_a_task(db_session, created_by=USER_CONSULTANT)
    payload = {
        "title": "Path A 资产",
        "summary": "摘要",
        "tags": [],
        "target_scope": "personal",
        "target_zone": "material",
        "confidentiality_level": "L2",
    }
    r1 = await client.post(
        f"/api/v1/ingest/{task_id}/confirm", headers=_hdr(USER_CONSULTANT), json=payload
    )
    assert r1.status_code == 200
    r2 = await client.post(
        f"/api/v1/ingest/{task_id}/confirm", headers=_hdr(USER_CONSULTANT), json=payload
    )
    assert r2.status_code == 409
    assert r2.json()["detail"]["denied_reason"] == "ingest_already_confirmed"


async def test_processing_task_present_but_unconfirmable(client, db_session):
    """仍 processing 的 Path A 任务出现在列表（可见状态），但确认被拒（409）。"""
    task_id = await _make_path_a_task(
        db_session, created_by=USER_CONSULTANT, status=IngestStatus.processing.value
    )
    listed = await client.get(f"{PENDING}?source=path_a_wecom", headers=_hdr(USER_CONSULTANT))
    item = next(i for i in listed.json()["items"] if i["id"] == str(task_id))
    assert item["status"] == "processing"
    r = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json={
            "title": "x",
            "summary": "y",
            "tags": [],
            "target_scope": "personal",
            "confidentiality_level": "L2",
        },
    )
    assert r.status_code == 409
    assert r.json()["detail"]["denied_reason"] == "ingest_processing_not_ready"

"""审计日志 API 与回填埋点测试（IMPLEMENT-09）。

覆盖：
1. 入库 confirm / 审核 approve / 预览 issue / Agent qa 成功后写入对应 action，且与触发动作共享同一 trace_id。
2. 纯 admin 业务写动作被拒写入 admin.business_denied（severity + extra.risk_level）。
3. A4 在 agent 渠道降级写入 agent.a4_original_denied（强审计）。
4. boss L5 原文预览写入强审计（preview.l5_used / l5_original_access）。
5. admin 视图对 L5 事件不暴露 target_id / 资产存在信息；boss 视图可见治理字段。
6. mark-processed 只改处理状态 + 追加处理事件，原始事实不变；非 admin 403；非 exception 422。
7. 普通业务用户访问 Admin Audit API 403。
8. trace 查询按可见性脱敏，不放大权限。
9. 审计响应不泄露内部敏感字段。
"""

from __future__ import annotations

import pytest

from app.main import app
from app.seed.dev_seed import (
    KA_COMPANY_L5,
    KA_PERSONAL,
    KA_PROJECT_ALPHA,
    KA_PROJECT_ALPHA_A4,
    KA_PROJECT_ALPHA_MATERIAL,
    KA_PROJECT_ALPHA_REVIEWABLE,
    PROJECT_ALPHA,
    REVIEW_SEED,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
    USER_PROJECT_MANAGER,
)
from app.services.llm_client import get_llm_client
from app.services.weknora_client import get_weknora_client

AUDIT = "/api/v1/admin/audit"

# Agent QA 现走真实 WeKnora 召回 + LLM；审计用例需注入 fake（不打网络）。
_ALPHA_KB = f"wk-kb-proj-{PROJECT_ALPHA}"
_ALPHA_ASSETS = [
    KA_PROJECT_ALPHA, KA_PROJECT_ALPHA_A4, KA_PROJECT_ALPHA_MATERIAL, KA_PROJECT_ALPHA_REVIEWABLE,
]


class _FakeWeKnora:
    def __init__(self, docs):
        self.docs = docs

    async def search(self, *, query, kb_ids, knowledge_ids=None, top_k=20, trace_id=None):
        out = []
        for i, d in enumerate(self.docs):
            if d["kb_id"] not in kb_ids:
                continue
            if knowledge_ids and d["knowledge_id"] not in knowledge_ids:
                continue
            out.append({"content": d["content"], "knowledge_id": d["knowledge_id"],
                        "chunk_index": 0, "score": round(1.0 - i * 0.01, 4), "seq": 0})
        return out

    async def hybrid_search(self, **_):
        return []


class _FakeLLM:
    provider = "deepseek"
    model = "deepseek-chat"

    async def chat_completion(self, messages, *, temperature=0.2, model=None, json_object=True, trace_id=None):
        return "【LLM 答案】基于本项目知识的综合回答。[1]"


@pytest.fixture(autouse=True)
def _agent_clients():
    docs = [
        {"knowledge_id": f"wk-doc-{aid}", "kb_id": _ALPHA_KB, "content": "Alpha 项目知识内容若干。"}
        for aid in _ALPHA_ASSETS
    ]
    app.dependency_overrides[get_weknora_client] = lambda: _FakeWeKnora(docs)
    app.dependency_overrides[get_llm_client] = lambda: _FakeLLM()
    yield
    app.dependency_overrides.pop(get_weknora_client, None)
    app.dependency_overrides.pop(get_llm_client, None)

_LEAK_TOKENS = [
    "storage_ref",
    "source_file_ref",
    "vector_id",
    "api_key",
    "dataset_id",
    "workflow_id",
    "kb_id",
    "bucket",
    "s3://",
    "oss://",
    "download_url",
    "file_url",
    "preview_token",
    "token_hash",
    "preview_entry_url",
]


def _hdr(user_id, trace=None):
    h = {"X-Dev-User-Id": str(user_id)}
    if trace:
        h["X-Trace-Id"] = trace
    return h


def _assert_no_leak(text: str):
    for t in _LEAK_TOKENS:
        assert t not in text, f"响应不应泄露 {t}"


async def _trace_actions(client, trace, viewer=USER_BOSS):
    """以治理视角取某 trace 下的 (action -> event) 映射。"""
    resp = await client.get(f"{AUDIT}/trace/{trace}", headers=_hdr(viewer))
    assert resp.status_code == 200
    return resp.json()["items"]


async def _do_ingest_confirm(client, trace):
    up = await client.post(
        "/api/v1/ingest/upload",
        headers=_hdr(USER_CONSULTANT, trace),
        files={"file": ("demo.txt", "审计测试文本内容\n第一行标题".encode(), "text/plain")},
    )
    task_id = up.json()["ingest_task_id"]
    await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_CONSULTANT, trace),
        json={
            "title": "审计测试个人资产",
            "summary": "占位",
            "tags": ["t"],
            "target_scope": "personal",
            "asset_type": "methodology",
            "confidentiality_level": "L2",
            "ai_access_level": "A1",
        },
    )


async def test_actions_written_with_shared_trace(client):
    """入库 confirm / 审核 approve / 预览 issue / Agent qa 成功后写入对应 action 且共享 trace_id。"""
    # 入库
    await _do_ingest_confirm(client, "trc-ingest")
    actions = {e["action"] for e in await _trace_actions(client, "trc-ingest")}
    assert "ingest.task_created" in actions
    assert "ingest.confirmed" in actions
    for e in await _trace_actions(client, "trc-ingest"):
        assert e["trace_id"] == "trc-ingest"

    # 审核 approve（REVIEW_SEED 审核人为经理B，已绑定证据）
    r = await client.post(
        f"/api/v1/reviews/{REVIEW_SEED}/approve", headers=_hdr(USER_PROJECT_MANAGER, "trc-review")
    )
    assert r.status_code == 200
    actions = {e["action"] for e in await _trace_actions(client, "trc-review")}
    assert "review.approved" in actions
    assert "asset.zone_changed" in actions

    # 预览 issue（consultant 对本人 personal 资产）
    p = await client.post(
        f"/api/v1/knowledge/{KA_PERSONAL}/preview", headers=_hdr(USER_CONSULTANT, "trc-preview")
    )
    assert p.status_code == 200
    actions = {e["action"] for e in await _trace_actions(client, "trc-preview")}
    assert "preview.issued" in actions

    # Agent qa
    q = await client.post(
        f"/api/v1/projects/{PROJECT_ALPHA}/qa",
        headers=_hdr(USER_CONSULTANT, "trc-agent"),
        json={"query": "供应链优化"},
    )
    assert q.status_code == 200
    actions = {e["action"] for e in await _trace_actions(client, "trc-agent")}
    assert "agent.called" in actions
    assert "agent.allowed" in actions


async def test_admin_business_denied_strong_audit(client):
    """纯 admin 发起入库被拒写入 admin.business_denied（severity + risk_level）。"""
    resp = await client.post(
        "/api/v1/ingest/upload",
        headers=_hdr(USER_ADMIN_ONLY, "trc-admindenied"),
        files={"file": ("x.docx", b"x", "application/msword")},
    )
    assert resp.status_code == 403
    events = await _trace_actions(client, "trc-admindenied")
    denied = next(e for e in events if e["action"] == "admin.business_denied")
    assert denied["log_type"] == "exception"
    assert denied["severity"] == "warning"
    assert denied["risk_level"] == "high"


async def test_a4_agent_downgrade_strong_audit(client):
    """A4 在 agent 渠道降级写入 agent.a4_original_denied（强审计标记）。"""
    q = await client.post(
        f"/api/v1/projects/{PROJECT_ALPHA}/qa",
        headers=_hdr(USER_CONSULTANT, "trc-a4"),
        json={"query": "A4 受限交付物"},
    )
    assert q.status_code == 200
    events = await _trace_actions(client, "trc-a4")
    a4 = [e for e in events if e["action"] == "agent.a4_original_denied"]
    assert len(a4) >= 1
    assert a4[0]["severity"] == "warning"
    assert a4[0]["risk_level"] == "high"
    assert str(KA_PROJECT_ALPHA_A4) in {e.get("target_id") for e in a4}


async def test_boss_l5_preview_strong_audit(client):
    """boss 对 L5 原文签发预览写入强审计（l5_original_access）。"""
    p = await client.post(
        f"/api/v1/knowledge/{KA_COMPANY_L5}/preview", headers=_hdr(USER_BOSS, "trc-l5")
    )
    assert p.status_code == 200
    events = await _trace_actions(client, "trc-l5")
    l5 = [e for e in events if e["action"] == "l5_original_access"]
    assert len(l5) >= 1
    assert l5[0]["risk_level"] == "high"


async def test_admin_view_masks_l5_but_governance_sees(client):
    """admin 视图对 L5 事件隐藏 target_id / asset 存在信息；boss 视图可见。"""
    await client.post(
        f"/api/v1/knowledge/{KA_COMPANY_L5}/preview", headers=_hdr(USER_BOSS, "trc-l5mask")
    )
    # boss（治理视图）：可见 target_id 与 extra.asset_id。
    gov = await client.get(f"{AUDIT}/trace/trc-l5mask", headers=_hdr(USER_DIRECTOR))
    assert gov.json()["view"] == "governance"
    gov_l5 = next(e for e in gov.json()["items"] if e["action"] == "l5_original_access")
    assert gov_l5["target_id"] is not None
    assert gov_l5["extra"] and "asset_id" in gov_l5["extra"]

    # admin（元数据视图）：L5 事件 target_id 被隐藏、无快照、extra 不含 asset_id。
    adm = await client.get(f"{AUDIT}/trace/trc-l5mask", headers=_hdr(USER_ADMIN_ONLY))
    assert adm.json()["view"] == "admin_metadata"
    adm_l5 = next(e for e in adm.json()["items"] if e["action"] == "l5_original_access")
    assert adm_l5["target_id"] is None
    assert adm_l5["before_snapshot"] is None and adm_l5["after_snapshot"] is None
    assert not (adm_l5["extra"] and "asset_id" in adm_l5["extra"])
    # 风险等级等安全元数据仍可见。
    assert adm_l5["risk_level"] == "high"
    _assert_no_leak(adm.text)


async def test_mark_processed_immutable_and_appends(client):
    """mark-processed 只改处理状态 + 追加处理事件，原始 action 不变。"""
    # 制造一条 exception 事件（admin 越权）。
    await client.post(
        "/api/v1/ingest/upload",
        headers=_hdr(USER_ADMIN_ONLY, "trc-markexc"),
        files={"file": ("x.docx", b"x", "application/msword")},
    )
    events = await _trace_actions(client, "trc-markexc")
    exc = next(e for e in events if e["action"] == "admin.business_denied")
    event_id = exc["id"]

    # admin 标记处理。
    m = await client.post(f"{AUDIT}/{event_id}/mark-processed", headers=_hdr(USER_ADMIN_ONLY))
    assert m.status_code == 200
    assert m.json()["is_processed"] is True
    assert m.json()["processed_by"] == str(USER_ADMIN_ONLY)

    # 原始事件 action 不变；trace 下追加了 audit.exception_processed。
    after = await _trace_actions(client, "trc-markexc")
    same = next(e for e in after if e["id"] == event_id)
    assert same["action"] == "admin.business_denied"  # 原始事实未被改写
    assert same["is_processed"] is True
    assert any(e["action"] == "audit.exception_processed" for e in after)


async def test_mark_processed_permission_and_non_exception(client):
    """mark-processed 仅 admin；boss 403；非 exception 事件 422。"""
    # 先产生一条 operation 事件（agent.called）与一条 exception 事件。
    await client.post(
        f"/api/v1/projects/{PROJECT_ALPHA}/qa",
        headers=_hdr(USER_CONSULTANT, "trc-mp"),
        json={"query": "供应链"},
    )
    events = await _trace_actions(client, "trc-mp")
    op_event = next(e for e in events if e["action"] == "agent.called")

    # boss（非 admin）标记处理 → 403。
    forbidden = await client.post(
        f"{AUDIT}/{op_event['id']}/mark-processed", headers=_hdr(USER_BOSS)
    )
    assert forbidden.status_code == 403

    # admin 标记一条 operation 事件 → 422（仅 exception 可处理）。
    bad = await client.post(
        f"{AUDIT}/{op_event['id']}/mark-processed", headers=_hdr(USER_ADMIN_ONLY)
    )
    assert bad.status_code == 422
    assert bad.json()["detail"]["denied_reason"] == "audit_event_not_exception"


async def test_normal_business_user_audit_forbidden(client):
    """普通业务用户（consultant）无审计查询权 → 403。"""
    resp = await client.get(AUDIT, headers=_hdr(USER_CONSULTANT))
    assert resp.status_code == 403
    assert resp.json()["detail"]["denied_reason"] == "audit_access_forbidden"


async def test_audit_list_filter_and_no_leak(client):
    """审计列表可按 action 过滤；boss 可查询；响应不泄露内部字段。"""
    await client.post(
        f"/api/v1/projects/{PROJECT_ALPHA}/qa",
        headers=_hdr(USER_CONSULTANT, "trc-list"),
        json={"query": "供应链"},
    )
    resp = await client.get(f"{AUDIT}?action=agent.allowed", headers=_hdr(USER_BOSS))
    assert resp.status_code == 200
    body = resp.json()
    assert body["view"] == "governance"
    assert body["total"] >= 1
    assert all(e["action"] == "agent.allowed" for e in body["items"])
    _assert_no_leak(resp.text)


async def test_value_level_sanitization_redacts_sensitive_values(client, db_session):
    """值级脱敏：敏感字符串值即便落在无害键名下，也不得写入 / 返回审计快照与 extra。

    client 与 db_session 共用同一函数级内存库；直接经唯一写入入口 record_event 注入，
    模拟业务侧误把敏感值塞进无害键名，再经治理视图（最宽）读回断言已被替换。
    """
    from app.schemas.enums import AuditAction, AuditLogType, CompanyRole
    from app.schemas.permission import CallerContext
    from app.services import audit as audit_service

    caller = CallerContext(
        user_id=USER_BOSS,
        is_active=True,
        active_company_roles={CompanyRole.boss.value},
        active_project_ids=set(),
    )
    await audit_service.record_event(
        db_session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.ingest_confirmed.value,
        trace_id="trc-valsan",
        target_type="knowledge_asset",
        before={"display": "https://example.com/private.docx"},
        after={"note": "file:///etc/secret", "kept": "L3"},
        extra={
            "safe_note": "s3://real-bucket/path/file.pdf",
            "nested": {"any_key": "internal://ingest/secret"},
            "deep_list": ["oss://b/x", "plain-value"],
            "denied_reason": "ok_reason",
        },
    )
    await db_session.commit()

    # 治理视图（最宽，可见快照 / 完整 extra）下取回，断言敏感值已被替换。
    gov = await client.get(f"{AUDIT}/trace/trc-valsan", headers=_hdr(USER_BOSS))
    assert gov.status_code == 200
    item = next(e for e in gov.json()["items"] if e["action"] == "ingest.confirmed")
    assert item["before_snapshot"]["display"] == "[redacted]"
    assert item["after_snapshot"]["note"] == "[redacted]"
    assert item["after_snapshot"]["kept"] == "L3"  # 安全值不受影响
    assert item["extra"]["safe_note"] == "[redacted]"
    assert item["extra"]["nested"]["any_key"] == "[redacted]"
    assert item["extra"]["deep_list"][0] == "[redacted]"
    assert item["extra"]["deep_list"][1] == "plain-value"
    assert item["extra"]["denied_reason"] == "ok_reason"  # 安全枚举式值保留

    # 原始响应文本不得包含任何敏感前缀 / 域名。
    text = gov.text
    for marker in ("s3://", "oss://", "file://", "internal://", "https://example.com"):
        assert marker not in text, f"响应不应泄露 {marker}"


async def test_trace_query_does_not_amplify_for_admin(client):
    """trace 查询不放大权限：admin 经 trace 查 L5 事件仍被脱敏（target_id 隐藏）。"""
    await client.post(
        f"/api/v1/knowledge/{KA_COMPANY_L5}/preview", headers=_hdr(USER_BOSS, "trc-noamp")
    )
    adm = await client.get(f"{AUDIT}/trace/trc-noamp", headers=_hdr(USER_ADMIN_ONLY))
    assert adm.status_code == 200
    l5 = next(e for e in adm.json()["items"] if e["action"] == "l5_original_access")
    assert l5["target_id"] is None
    _assert_no_leak(adm.text)

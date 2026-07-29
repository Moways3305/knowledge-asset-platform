"""WorkBuddy MCP 工具核心测试：安全字段投影 + 错误收口 + 配置 fail-closed。"""

from __future__ import annotations

import httpx
import pytest

from workbuddy_mcp.config import load_config
from workbuddy_mcp.kap_client import (
    KapClient,
    KapError,
    answer_from_knowledge,
    get_knowledge_summary,
    get_project_brief,
    list_accessible_projects,
    list_my_todos,
    list_original_access_requests,
    list_pending_reviews,
    list_project_knowledge,
    list_recent_knowledge,
    search_knowledge,
)


def _client(handler):
    transport = httpx.MockTransport(handler)
    http = httpx.Client(base_url="http://kap.test", transport=transport)
    cfg = load_config({"KAP_BASE_URL": "http://kap.test", "KAP_AGENT_TOKEN": "kgw_x"})
    return KapClient(cfg, client=http)


def test_load_config_fails_closed_when_missing():
    with pytest.raises(RuntimeError) as e:
        load_config({"KAP_BASE_URL": "http://kap.test"})
    assert "KAP_AGENT_TOKEN" in str(e.value)


def test_search_projects_to_safe_card_fields():
    def handler(request):
        assert request.headers["authorization"] == "Bearer kgw_x"
        assert "x-platform-user-id" not in request.headers
        return httpx.Response(
            200,
            json={
                "cards": [
                    {
                        "asset_id": "a1",
                        "title": "T",
                        "asset_type": "case",
                        "scope": "project",
                        "zone": "asset",
                        "confidentiality_level": "L2",
                        "one_liner": "x",
                        "detailed": "y",
                        "relevance_score": 0.9,
                        "can_view_original": False,
                        "weknora_doc_id": "wk-doc-LEAK",
                        "storage_ref": "s3://LEAK",
                    }
                ]
            },
        )

    client = _client(handler)
    cards = search_knowledge(client, "q", scope="project")
    assert cards[0]["asset_id"] == "a1"
    assert "weknora_doc_id" not in cards[0]
    assert "storage_ref" not in cards[0]


def test_answer_returns_answer_and_safe_citations():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "answer": "ans",
                "citations": [
                    {
                        "asset_id": "a1",
                        "asset_title": "T",
                        "scope": "company",
                        "snippet": "s",
                        "citation_order": 1,
                        "chunk_id": "LEAK",
                    }
                ],
            },
        )

    client = _client(handler)
    out = answer_from_knowledge(client, "q")
    assert out["answer"] == "ans"
    assert "chunk_id" not in out["citations"][0]


def test_projects_safe_fields():
    def handler(request):
        return httpx.Response(
            200, json={"items": [{"project_id": "p1", "name": "N", "status": "active"}]}
        )

    client = _client(handler)
    out = list_accessible_projects(client)
    assert out == [{"project_id": "p1", "name": "N", "status": "active"}]


def test_error_is_sanitized():
    def handler(request):
        return httpx.Response(
            403,
            json={"detail": {"denied_reason": "caller_unresolved", "message": "secret"}},
        )

    client = _client(handler)
    with pytest.raises(KapError) as e:
        search_knowledge(client, "q")
    msg = str(e.value)
    assert "无访问权限" in msg
    for leak in ("caller_unresolved", "secret", "kgw_x", "kap.test"):
        assert leak not in msg


# --------------------- 只读工作台工具（PBC-37）---------------------
# 后端故意多回内部字段，断言 MCP 只透出白名单字段。
_LEAK_EXTRA = {
    "storage_ref": "s3://LEAK",
    "source_file_ref": "LEAK",
    "weknora_doc_id": "wk-doc-LEAK",
    "weknora_kb_id": "wk-kb-LEAK",
    "chunk_id": "LEAK",
    "download_url": "http://LEAK",
    "preview_entry_url": "http://LEAK",
    "token_hash": "LEAK",
}


def _assert_no_leak(obj):
    flat = repr(obj)
    for k in _LEAK_EXTRA:
        assert k not in flat


def test_todos_projection():
    def handler(request):
        assert request.headers["authorization"] == "Bearer kgw_user"
        assert "x-platform-user-id" not in request.headers
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "todo_id": "review:1",
                        "type": "review",
                        "title": "待审核知识资产",
                        "status": "pending_reviewer",
                        "priority": "normal",
                        "project_id": "p1",
                        "project_name": "Alpha",
                        "asset_id": "a1",
                        "asset_title": "T",
                        "created_at": "2026-06-01T00:00:00Z",
                        **_LEAK_EXTRA,
                    }
                ],
                "counts": {
                    "reviews": 1,
                    "ingest": 0,
                    "original_access_mine": 0,
                    "original_access_inbox": 0,
                    "secret_extra": 9,
                },
            },
        )

    client = _client(handler)
    out = list_my_todos(client, bearer="kgw_user")
    assert out["items"][0]["todo_id"] == "review:1"
    assert "secret_extra" not in out["counts"]
    _assert_no_leak(out)


def test_recent_knowledge_projection():
    def handler(request):
        assert request.url.params["scope"] == "company"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "asset_id": "a1",
                        "title": "T",
                        "scope": "company",
                        "zone": "asset",
                        "asset_type": "case",
                        "confidentiality_level": "L2",
                        "one_liner": "x",
                        "updated_at": "2026-06-01T00:00:00Z",
                        "project_id": None,
                        "project_name": None,
                        "can_view_original": True,
                        **_LEAK_EXTRA,
                    }
                ]
            },
        )

    client = _client(handler)
    out = list_recent_knowledge(client, scope="company", bearer="kgw_user")
    assert out[0]["asset_id"] == "a1"
    assert set(out[0].keys()) == {
        "asset_id",
        "title",
        "scope",
        "zone",
        "asset_type",
        "confidentiality_level",
        "one_liner",
        "updated_at",
        "project_id",
        "project_name",
        "can_view_original",
    }
    _assert_no_leak(out)


def test_knowledge_summary_projection_no_original():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "asset_id": "a1",
                "title": "T",
                "scope": "company",
                "zone": "asset",
                "asset_type": "case",
                "confidentiality_level": "L2",
                "summary": "safe summary",
                "key_points": ["k1"],
                "tags": ["t1"],
                "project_id": None,
                "project_name": None,
                "access_layer": "summary",
                "can_view_original": True,
                "existing_original_request_status": None,
                "original_text": "LEAK ORIGINAL",
                **_LEAK_EXTRA,
            },
        )

    client = _client(handler)
    out = get_knowledge_summary(client, "a1", bearer="kgw_user")
    assert out["summary"] == "safe summary"
    assert "original_text" not in out
    _assert_no_leak(out)


def test_project_knowledge_passes_tags_and_projects():
    def handler(request):
        assert request.url.params.get_list("tags") == ["供应链", "流程优化"]
        return httpx.Response(
            200, json={"items": [{"asset_id": "a1", "title": "T", **_LEAK_EXTRA}]}
        )

    client = _client(handler)
    out = list_project_knowledge(client, "p1", tags=["供应链", "流程优化"], bearer="kgw_user")
    assert out[0]["asset_id"] == "a1"
    _assert_no_leak(out)


def test_project_brief_projection():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "project_id": "p1",
                "name": "Alpha",
                "status": "active",
                "phase": "交付",
                "my_role": "consultant",
                "knowledge_count": 3,
                "recent_asset_count": 1,
                "pending_review_count": 0,
                "pending_original_request_count": 0,
                "client_name": "LEAK CLIENT",
                **_LEAK_EXTRA,
            },
        )

    client = _client(handler)
    out = get_project_brief(client, "p1", bearer="kgw_user")
    assert "client_name" not in out
    assert out["my_role"] == "consultant"
    _assert_no_leak(out)


def test_pending_reviews_projection():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "review_id": "r1",
                        "review_type": "material_to_asset",
                        "status": "pending_reviewer",
                        "asset_id": "a1",
                        "asset_title": "T",
                        "project_id": "p1",
                        "project_name": "Alpha",
                        "created_at": "2026-06-01T00:00:00Z",
                        "due_hint": "待审核人处理",
                        "review_comment": "internal note LEAK",
                        **_LEAK_EXTRA,
                    }
                ]
            },
        )

    client = _client(handler)
    out = list_pending_reviews(client, bearer="kgw_user")
    assert out[0]["review_id"] == "r1"
    assert "review_comment" not in out[0]
    _assert_no_leak(out)


def test_project_tools_404_is_sanitized():
    """无权/不存在项目后端均回 404 → MCP 收口为安全文案，不回显内部细节。"""

    def handler(request):
        return httpx.Response(
            404,
            json={
                "detail": {
                    "denied_reason": "project_not_found",
                    "message": "项目不存在或不可用",
                    "trace_id": "trace-LEAK",
                    "internal_url": "http://kap.internal/LEAK",
                }
            },
        )

    client = _client(handler)
    for call in (
        lambda: list_project_knowledge(client, "p1", bearer="kgw_user"),
        lambda: get_project_brief(client, "p1", bearer="kgw_user"),
    ):
        with pytest.raises(KapError) as e:
            call()
        msg = str(e.value)
        for leak in (
            "project_not_found",
            "trace-LEAK",
            "internal_url",
            "http://",
            "kap.test",
        ):
            assert leak not in msg


def test_original_access_projection_and_box_param():
    def handler(request):
        assert request.url.params["box"] == "inbox"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "request_id": "req1",
                        "box": "inbox",
                        "status": "pending",
                        "asset_id": "a1",
                        "asset_title": "T",
                        "requester_name": "顾问A",
                        "reviewer_name": None,
                        "reason": "需要原文",
                        "created_at": "2026-06-01T00:00:00Z",
                        "reviewed_at": None,
                        "expires_at": None,
                        "grant_token": "LEAK",
                        **_LEAK_EXTRA,
                    }
                ]
            },
        )

    client = _client(handler)
    out = list_original_access_requests(client, box="inbox", bearer="kgw_user")
    assert out[0]["request_id"] == "req1"
    assert "grant_token" not in out[0]
    _assert_no_leak(out)

"""WorkBuddy MCP 工具核心测试：安全字段投影 + 错误收口 + 配置 fail-closed。"""

from __future__ import annotations

import httpx
import pytest

from workbuddy_mcp.config import load_config
from workbuddy_mcp.kap_client import (
    KapClient,
    KapError,
    answer_from_knowledge,
    list_accessible_projects,
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
            403, json={"detail": {"denied_reason": "caller_unresolved", "message": "secret"}}
        )

    client = _client(handler)
    with pytest.raises(KapError) as e:
        search_knowledge(client, "q")
    msg = str(e.value)
    assert "无访问权限" in msg
    for leak in ("caller_unresolved", "secret", "kgw_x", "kap.test"):
        assert leak not in msg

"""顾问只读模型选项 API 测试（PBC-38）。

覆盖：active 业务用户可读；纯 admin / inactive 不可读；响应无真实 model_id/api_key/base_url；
is_default 标记正确（仅平台默认）；未配置默认时 default_missing=True 仍返回列表；
disabled / 非默认模型不被误标 is_default；type 过滤可取 embedding / rerank。
"""

from __future__ import annotations

import uuid

import pytest

from app.api.deps import get_caller_context
from app.main import app
from app.schemas.permission import CallerContext
from app.seed.dev_seed import USER_ADMIN_ONLY, USER_CONSULTANT
from app.services import weknora_defaults
from app.services.weknora_client import get_weknora_client
from app.services.weknora_models import _model_ref

URL = "/api/v1/weknora/model-options"
_RAW_IDS = ["mid-emb", "mid-emb2", "mid-rerank", "mid-disabled", "mid-chat"]


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


class FakeWK:
    def __init__(self):
        self.models = {
            "mid-emb": _m("mid-emb", "text-embedding-v3", "Embedding"),
            "mid-emb2": _m("mid-emb2", "bge-large", "Embedding"),
            "mid-rerank": _m("mid-rerank", "rerank-v3", "Rerank"),
            "mid-disabled": _m("mid-disabled", "embedding-legacy", "Embedding", status="inactive"),
            "mid-chat": _m("mid-chat", "deepseek-chat", "KnowledgeQA"),
        }

    async def list_models(self, *, trace_id=None):
        return list(self.models.values())


def _m(mid, name, wk_type, *, status="active"):
    return {
        "id": mid,
        "name": name,
        "type": wk_type,
        "source": "remote",
        "status": status,
        "parameters": {"provider": "aliyun"},
    }


@pytest.fixture
def wk(monkeypatch):
    fake = FakeWK()
    monkeypatch.setattr("app.api.weknora_options.weknora_enabled", lambda: True)
    app.dependency_overrides[get_weknora_client] = lambda: fake
    yield fake
    app.dependency_overrides.pop(get_weknora_client, None)


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------
async def test_consultant_can_read(client, wk):
    r = await client.get(URL, headers=_hdr(USER_CONSULTANT))
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 5
    for it in body["items"]:
        assert it["model_ref"] and "model_id" not in it and "id" not in it


async def test_pure_admin_forbidden(client, wk):
    # 产品判断：本端点服务业务入库 UX；纯 admin（非业务用户）走 /admin/weknora/models，
    # 在此 403——不扩大其业务知识权限。
    r = await client.get(URL, headers=_hdr(USER_ADMIN_ONLY))
    assert r.status_code == 403
    assert r.json()["detail"]["denied_reason"] == "weknora_options_forbidden"


async def test_inactive_forbidden(client, wk):
    # inactive（以及生产环境下的 anonymous，resolve_current_user 先返回 401）不可读。
    inactive = CallerContext(
        user_id=uuid.uuid4(),
        is_active=False,
        active_company_roles={"consultant"},
        active_project_ids=set(),
        active_project_roles={},
    )
    app.dependency_overrides[get_caller_context] = lambda: inactive
    try:
        r = await client.get(URL, headers=_hdr(USER_CONSULTANT))
        assert r.status_code == 403
        assert r.json()["detail"]["denied_reason"] == "weknora_options_forbidden"
    finally:
        app.dependency_overrides.pop(get_caller_context, None)


# ---------------------------------------------------------------------------
# 安全：无真实 id / secret
# ---------------------------------------------------------------------------
async def test_no_raw_id_or_secret_leak(client, wk):
    r = await client.get(URL, headers=_hdr(USER_CONSULTANT))
    assert r.status_code == 200
    for token in _RAW_IDS + ["api_key", "base_url", "sk-"]:
        assert token not in r.text


# ---------------------------------------------------------------------------
# is_default 标记 + default_missing
# ---------------------------------------------------------------------------
async def test_is_default_marked_only_for_platform_default(client, wk, db_session):
    await weknora_defaults.set_defaults(
        db_session,
        embedding_model_id="mid-emb",
        rerank_model_id="mid-rerank",
        chat_model_id="mid-chat",
        multimodal_id=None,
        updated_by=None,
    )
    await db_session.commit()
    r = await client.get(URL, headers=_hdr(USER_CONSULTANT))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["default_missing"] is False
    by_ref = {it["model_ref"]: it for it in body["items"]}
    assert by_ref[_model_ref("mid-emb")]["is_default"] is True
    assert by_ref[_model_ref("mid-rerank")]["is_default"] is True
    # 非默认 embedding 不被标记。
    assert by_ref[_model_ref("mid-emb2")]["is_default"] is False
    # disabled 模型 enabled=False，且非默认 → is_default=False（不被误标）。
    disabled = by_ref[_model_ref("mid-disabled")]
    assert disabled["enabled"] is False
    assert disabled["is_default"] is False


async def test_default_missing_when_unset_still_lists(client, wk):
    # 未配置默认（无 defaults 行）→ 仍返回列表，但 default_missing=True，且无 is_default。
    r = await client.get(URL, headers=_hdr(USER_CONSULTANT))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["default_missing"] is True
    assert len(body["items"]) == 5
    assert all(it["is_default"] is False for it in body["items"])


async def test_default_missing_when_chat_unset_even_if_embedding_configured(client, wk, db_session):
    await weknora_defaults.set_defaults(
        db_session,
        embedding_model_id="mid-emb",
        rerank_model_id=None,
        chat_model_id=None,
        multimodal_id=None,
        updated_by=None,
    )
    await db_session.commit()
    r = await client.get(URL, headers=_hdr(USER_CONSULTANT))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["default_missing"] is True
    by_ref = {it["model_ref"]: it for it in body["items"]}
    assert by_ref[_model_ref("mid-emb")]["is_default"] is True


# ---------------------------------------------------------------------------
# type 过滤
# ---------------------------------------------------------------------------
async def test_type_filter_rerank(client, wk):
    r = await client.get(f"{URL}?type=rerank", headers=_hdr(USER_CONSULTANT))
    assert r.status_code == 200
    items = r.json()["items"]
    assert items and all(it["type"] == "rerank" for it in items)


async def test_type_filter_embedding(client, wk):
    r = await client.get(f"{URL}?type=embedding", headers=_hdr(USER_CONSULTANT))
    assert r.status_code == 200
    items = r.json()["items"]
    assert {it["model_ref"] for it in items} == {
        _model_ref("mid-emb"),
        _model_ref("mid-emb2"),
        _model_ref("mid-disabled"),
    }

"""PBC-46 KAP 内容生成模型持久化、安全边界与调用链测试。"""

from __future__ import annotations

import json

from sqlalchemy import select

from app.models.audit import AuditEvent
from app.models.generation_model import ContentGenerationModel
from app.seed.dev_seed import USER_ADMIN_ONLY, USER_CONSULTANT
from app.services import generation_models
from app.services.llm_client import LLMClient, LLMError, NullLLMClient

BASE = "/api/v1/admin/generation"
SECRET = "SECRET-LIKE-generation-key"
URL = "https://generation.example.test/v1"


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


def _payload(**overrides):
    body = {
        "display_name": "DeepSeek 内容生成",
        "provider": "deepseek",
        "model_name": "deepseek-chat",
        "base_url": URL,
        "api_key": SECRET,
        "enabled": True,
        "make_default": True,
    }
    body.update(overrides)
    return body


async def _create(client, **overrides):
    return await client.post(
        f"{BASE}/models", headers=_hdr(USER_ADMIN_ONLY), json=_payload(**overrides)
    )


async def test_admin_create_default_encrypts_secrets_and_returns_safe_fields(client, db_session):
    response = await _create(client)
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "model_ref",
        "display_name",
        "provider",
        "model_name",
        "enabled",
        "is_default",
    }
    assert body["is_default"] is True
    assert SECRET not in response.text
    assert URL not in response.text

    row = (await db_session.execute(select(ContentGenerationModel))).scalar_one()
    assert row.api_key_ciphertext != SECRET
    assert row.base_url_ciphertext != URL
    assert SECRET not in row.api_key_ciphertext
    assert URL not in row.base_url_ciphertext

    event = (
        await db_session.execute(
            select(AuditEvent).where(AuditEvent.action == "generation_model.created")
        )
    ).scalar_one()
    serialized = json.dumps(event.extra)
    assert body["model_ref"] in serialized
    assert SECRET not in serialized
    assert URL not in serialized


async def test_business_user_cannot_write_generation_models(client):
    create = await client.post(f"{BASE}/models", headers=_hdr(USER_CONSULTANT), json=_payload())
    assert create.status_code == 403
    for method, path, body in (
        ("PUT", f"{BASE}/models/fake", _payload(make_default=False)),
        ("DELETE", f"{BASE}/models/fake", None),
        ("PUT", f"{BASE}/default-model", {"model_ref": None}),
        ("POST", f"{BASE}/models/fake/test", {}),
    ):
        response = await client.request(method, path, headers=_hdr(USER_CONSULTANT), json=body)
        assert response.status_code == 403


async def test_blank_api_key_and_url_retain_stored_ciphertext(client, db_session):
    created = (await _create(client)).json()
    row = (await db_session.execute(select(ContentGenerationModel))).scalar_one()
    key_ciphertext = row.api_key_ciphertext
    url_ciphertext = row.base_url_ciphertext

    response = await client.put(
        f"{BASE}/models/{created['model_ref']}",
        headers=_hdr(USER_ADMIN_ONLY),
        json={
            "display_name": "更新后的名称",
            "provider": "deepseek",
            "model_name": "deepseek-chat",
            "base_url": "",
            "api_key": "",
            "enabled": True,
        },
    )
    assert response.status_code == 200
    await db_session.refresh(row)
    assert row.api_key_ciphertext == key_ciphertext
    assert row.base_url_ciphertext == url_ciphertext
    assert SECRET not in response.text
    assert URL not in response.text


async def test_disabled_model_cannot_be_or_remain_default(client):
    created = (await _create(client)).json()
    disabled = await client.put(
        f"{BASE}/models/{created['model_ref']}",
        headers=_hdr(USER_ADMIN_ONLY),
        json={
            "display_name": created["display_name"],
            "provider": created["provider"],
            "model_name": created["model_name"],
            "enabled": False,
        },
    )
    assert disabled.status_code == 409

    second = (await _create(client, display_name="备用", make_default=False, enabled=False)).json()
    set_default = await client.put(
        f"{BASE}/default-model",
        headers=_hdr(USER_ADMIN_ONLY),
        json={"model_ref": second["model_ref"]},
    )
    assert set_default.status_code == 422


async def test_default_must_be_cleared_before_delete(client):
    created = (await _create(client)).json()
    denied = await client.delete(
        f"{BASE}/models/{created['model_ref']}", headers=_hdr(USER_ADMIN_ONLY)
    )
    assert denied.status_code == 409
    cleared = await client.put(
        f"{BASE}/default-model",
        headers=_hdr(USER_ADMIN_ONLY),
        json={"model_ref": None},
    )
    assert cleared.status_code == 200
    deleted = await client.delete(
        f"{BASE}/models/{created['model_ref']}", headers=_hdr(USER_ADMIN_ONLY)
    )
    assert deleted.status_code == 200


async def test_connection_result_is_safe_on_success_and_failure(client, monkeypatch):
    created = (await _create(client)).json()

    async def ok(self, *args, **kwargs):
        return "OK"

    monkeypatch.setattr(LLMClient, "chat_completion", ok)
    success = await client.post(
        f"{BASE}/models/{created['model_ref']}/test",
        headers=_hdr(USER_ADMIN_ONLY),
        json={},
    )
    assert success.status_code == 200
    assert success.json()["success"] is True

    async def fail(self, *args, **kwargs):
        raise LLMError("upstream_failed", f"{SECRET} {URL}")

    monkeypatch.setattr(LLMClient, "chat_completion", fail)
    failed = await client.post(
        f"{BASE}/models/{created['model_ref']}/test",
        headers=_hdr(USER_ADMIN_ONLY),
        json={},
    )
    assert failed.status_code == 200
    assert failed.json()["success"] is False
    assert SECRET not in failed.text
    assert URL not in failed.text
    assert "upstream_failed" not in failed.text


async def test_product_config_without_default_keeps_summary_pending(client):
    created = await _create(client, make_default=False)
    assert created.status_code == 201
    upload = await client.post(
        "/api/v1/ingest/upload",
        headers=_hdr(USER_CONSULTANT),
        files={"file": ("note.md", b"# title\nextracted body", "text/markdown")},
    )
    assert upload.status_code == 200
    task_id = upload.json()["ingest_task_id"]
    result = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    body = result.json()
    assert body["summary_status"] == "pending_model_config"
    assert body["summary"] is None
    assert body["extracted_text_preview"]


async def test_persisted_default_credentials_drive_content_generation(client, monkeypatch):
    captured = {}

    async def generated(self, *args, **kwargs):
        captured.update(
            api_key=self._api_key,
            base_url=self._base,
            model=self.model,
        )
        return json.dumps(
            {
                "one_liner": "生成的一句话摘要",
                "detailed": "由数据库默认内容生成模型生成的详细摘要。",
                "key_points": ["数据库默认模型"],
                "tags": ["内容生成"],
                "asset_type": "methodology",
                "confidentiality_level": "L2",
                "ai_access_level": "A2",
                "topic": "内容生成配置",
                "subject_or_client": "通用",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(LLMClient, "chat_completion", generated)
    assert (await _create(client)).status_code == 201
    upload = await client.post(
        "/api/v1/ingest/upload",
        headers=_hdr(USER_CONSULTANT),
        files={"file": ("note.md", b"# title\nbody", "text/markdown")},
    )
    task_id = upload.json()["ingest_task_id"]
    result = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    assert result.json()["summary_status"] == "generated"
    assert result.json()["summary"] == "由数据库默认内容生成模型生成的详细摘要。"
    assert captured == {"api_key": SECRET, "base_url": URL, "model": "deepseek-chat"}
    assert SECRET not in result.text
    assert URL not in result.text


async def test_public_options_expose_only_safe_fields(client):
    await _create(client)
    response = await client.get("/api/v1/generation/model-options", headers=_hdr(USER_CONSULTANT))
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert set(item) == {
        "model_ref",
        "display_name",
        "provider",
        "model_name",
        "enabled",
        "is_default",
    }
    for forbidden in (SECRET, URL, "ciphertext", "api_key", "base_url"):
        assert forbidden not in response.text


async def test_invalid_sensitive_inputs_are_not_echoed(client):
    response = await _create(
        client,
        base_url="SECRET-LIKE-not-a-url",
        api_key="SECRET-LIKE-invalid-key",
    )
    assert response.status_code == 422
    assert "SECRET-LIKE-not-a-url" not in response.text
    assert "SECRET-LIKE-invalid-key" not in response.text


async def test_env_fallback_stops_after_product_configuration_exists(db_session, monkeypatch):
    env_client = LLMClient(
        provider="deepseek",
        api_key="env-secret",
        base_url="https://env.example.test/v1",
        model="env-model",
    )
    monkeypatch.setattr(generation_models, "get_llm_client", lambda: env_client)
    assert await generation_models.resolve_generation_llm_client(db_session) is env_client

    await generation_models.create_model(
        db_session,
        display_name="产品配置",
        provider="deepseek",
        model_name="product-model",
        base_url=URL,
        api_key=SECRET,
        enabled=True,
        make_default=False,
        actor_id=USER_ADMIN_ONLY,
    )
    await db_session.commit()
    resolved = await generation_models.resolve_generation_llm_client(db_session)
    assert isinstance(resolved, NullLLMClient)


async def test_safe_project_qa_options_lists_default_model_with_suffix_and_system_default(
    db_session, monkeypatch
):
    """默认模型作为独立选项列出并标注（默认）；"系统默认模型"作为跟随平台默认的选项保留。"""
    env_client = LLMClient(
        provider="deepseek",
        api_key="env-secret",
        base_url="https://env.example.test/v1",
        model="env-model",
    )
    monkeypatch.setattr(generation_models, "get_llm_client", lambda: env_client)

    default = await generation_models.create_model(
        db_session,
        display_name="deepseek-v4-flash",
        provider="deepseek",
        model_name="deepseek-v4-flash",
        base_url=URL,
        api_key=SECRET,
        enabled=True,
        make_default=True,
        actor_id=USER_ADMIN_ONLY,
    )
    other = await generation_models.create_model(
        db_session,
        display_name="备用模型",
        provider="deepseek",
        model_name="backup-chat",
        base_url=URL,
        api_key=SECRET,
        enabled=True,
        make_default=False,
        actor_id=USER_ADMIN_ONLY,
    )
    await db_session.commit()

    items = await generation_models.safe_project_qa_options(db_session, env_client)

    # 第一项：系统默认模型（跟随平台默认）。
    assert items[0]["model_ref"] == "system_default"
    assert items[0]["display_name"] == "系统默认模型"
    assert items[0]["is_default"] is True
    # 默认模型作为独立选项列出，标注（默认）后缀。
    default_item = next(it for it in items if it["model_ref"] == default["model_ref"])
    assert default_item["display_name"] == "deepseek-v4-flash（默认）"
    assert default_item["is_default"] is True
    # 非默认模型也列出。
    other_item = next(it for it in items if it["model_ref"] == other["model_ref"])
    assert other_item["display_name"] == "备用模型"
    assert other_item["is_default"] is False
    # 默认模型没有被跳过：列表含 1 个 system_default + 2 个具体模型 = 3 项。
    assert len(items) == 3
    for forbidden in (SECRET, URL, "ciphertext", "api_key"):
        assert forbidden not in json.dumps(items, ensure_ascii=False)


async def test_safe_project_qa_options_without_default_model_still_lists_enabled_chat(
    db_session, monkeypatch
):
    """无默认模型配置时（settings 存在但 default_model_id 为空），不出现"系统默认模型"
    选项；仍列出所有 enabled chat 模型（无（默认）后缀，is_default=False）。"""
    env_client = LLMClient(
        provider="deepseek",
        api_key="env-secret",
        base_url="https://env.example.test/v1",
        model="env-model",
    )
    monkeypatch.setattr(generation_models, "get_llm_client", lambda: env_client)

    created = await generation_models.create_model(
        db_session,
        display_name="仅启用非默认",
        provider="deepseek",
        model_name="non-default-chat",
        base_url=URL,
        api_key=SECRET,
        enabled=True,
        make_default=False,
        actor_id=USER_ADMIN_ONLY,
    )
    await db_session.commit()

    items = await generation_models.safe_project_qa_options(db_session, env_client)
    # settings 已建但 default_model_id=None → 无"系统默认模型"选项，列表仅含具体模型。
    assert len(items) == 1
    assert items[0]["model_ref"] == created["model_ref"]
    assert items[0]["display_name"] == "仅启用非默认"
    assert items[0]["is_default"] is False
    assert "（默认）" not in items[0]["display_name"]

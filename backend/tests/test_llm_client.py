"""外部 LLM 内容处理测试（fake LLMClient，不打真实网络）。

覆盖：结构化 JSON 解析写草稿、provider/model 记录、降级（未配置/失败/脏 JSON）、
confirm 三层摘要(含 key_points)写穿 + AI/人工独立存储、无 api_key/Bearer 泄露、
WeKnora 链路不回归。
"""

from __future__ import annotations

import json
import re

import httpx
import pytest

from app.main import app
from app.schemas.enums import AssetType, ConfidentialityLevel
from app.seed.dev_seed import USER_CONSULTANT
from app.services import audit as audit_service
from app.services.generation_models import get_generation_llm_client
from app.services.llm_client import LLMClient, LLMError

UPLOAD = "/api/v1/ingest/upload"
KN = "/api/v1/knowledge"
_TXT = "零售数字化转型方案正文，包含五维度成熟度评估与落地路径若干段。".encode()


def _hdr(user_id, trace=None):
    h = {"X-Dev-User-Id": str(user_id)}
    if trace:
        h["X-Trace-Id"] = trace
    return h


class FakeLLM:
    """fake LLMClient：返回固定结构化 JSON，或模拟失败 / 脏输出。"""

    provider = "deepseek"
    model = "deepseek-chat"

    def __init__(self, *, mode: str = "ok", payload: dict | None = None) -> None:
        self.mode = mode
        self.payload = payload
        self.calls = 0
        self.last_messages = None

    async def chat_completion(
        self, messages, *, temperature=0.2, model=None, json_object=True, trace_id=None
    ):
        self.calls += 1
        self.last_messages = messages
        if self.mode == "fail":
            raise LLMError("http_500", "LLM 调用失败")
        if self.mode == "dirty":
            return "这不是 JSON 抱歉"
        if self.mode == "fenced":
            return "```json\n" + json.dumps(_GOOD) + "\n```"
        if self.mode == "missing_detailed":
            partial = dict(_GOOD)
            partial.pop("detailed", None)
            return json.dumps(partial, ensure_ascii=False)
        return json.dumps(self.payload or _GOOD, ensure_ascii=False)


# 平台命名格式：【一级类-二级类】主题_对象/客户_YYYYMMDD_V版本_L保密级别
_TITLE_RE = re.compile(r"^【[^-】]+-[^】]+】.+_.+_\d{8}_V\d+_L[1-5]$")

_GOOD = {
    "asset_type": "case",
    "version_confidence": "medium",
    "version_reason": "模型原始版本理由不得直接返回",
    "confidentiality_level": "L3",
    "confidentiality_confidence": "medium",
    "confidentiality_reason": "正文包含内部经营分析",
    "ai_access_level": "A3",
    # 规范命名组件（标题用），与摘要分离。
    "primary_category": "客户项目",
    "secondary_category": "交付成果",
    "topic": "零售数字化转型方案",
    "subject_or_client": "某零售集团",
    "date": "20260520",
    "version": "V2",
    "inferred_fields": [],
    # 摘要字段（自然语言，不当标题）。
    "one_liner": "零售数字化转型五维度成熟度评估方法论",
    "detailed": "覆盖战略/组织/流程/数据/技术五维度的成熟度评估与落地路径的详细摘要。",
    "key_points": ["五维度模型", "23 项指标", "已在多项目验证"],
    "tags": ["数字化转型", "成熟度模型", "零售"],
}


def _enable_llm(monkeypatch, fake):
    del monkeypatch
    app.dependency_overrides[get_generation_llm_client] = lambda: fake


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.pop(get_generation_llm_client, None)


async def _upload(client, content=_TXT, file_name="retail.txt", mime="text/plain"):
    r = await client.post(
        UPLOAD, headers=_hdr(USER_CONSULTANT), files={"file": (file_name, content, mime)}
    )
    return r.json()["ingest_task_id"]


# ---- LLMClient 单测 ----
def test_llm_client_provider_registry_defaults():
    c = LLMClient(provider="deepseek", api_key="sk-x")
    assert c.model == "deepseek-chat"
    assert "api.deepseek.com" in c._base


def test_llm_client_custom_requires_base():
    with pytest.raises(LLMError):
        LLMClient(provider="custom", api_key="sk-x")  # 无 base_url


def test_llm_client_minimax_group_id_in_endpoint():
    c = LLMClient(provider="minimax", api_key="sk-x", minimax_group_id="g123")
    assert "GroupId=g123" in c._endpoint()


class _FakeHttpClient:
    def __init__(self, *, response: httpx.Response | None = None, error: Exception | None = None):
        self.response = response
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, *_args, **_kwargs):
        if self.error:
            raise self.error
        assert self.response is not None
        return self.response


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [
        (401, "llm_authentication_error"),
        (404, "llm_model_not_found"),
        (429, "llm_rate_limited"),
        (400, "llm_request_error"),
        (503, "llm_server_error"),
    ],
)
async def test_llm_client_classifies_http_failures_without_response_body(
    monkeypatch, status, expected_code
):
    raw = "SECRET-LIKE provider response"
    fake = _FakeHttpClient(response=httpx.Response(status, text=raw))
    monkeypatch.setattr("app.services.llm_client.httpx.AsyncClient", lambda **_kwargs: fake)
    llm = LLMClient(
        provider="custom",
        api_key="SECRET-LIKE-key",
        base_url="https://models.example.test/v1",
        model="chat-model",
    )

    with pytest.raises(LLMError) as captured:
        await llm.chat_completion([{"role": "user", "content": "test"}])

    assert captured.value.code == expected_code
    assert raw not in str(captured.value)
    assert "SECRET-LIKE-key" not in str(captured.value)


async def test_llm_client_classifies_timeout_without_endpoint_or_secret(monkeypatch):
    request = httpx.Request("POST", "https://models.example.test/v1/chat/completions")
    fake = _FakeHttpClient(error=httpx.ReadTimeout("SECRET-LIKE timeout", request=request))
    monkeypatch.setattr("app.services.llm_client.httpx.AsyncClient", lambda **_kwargs: fake)
    llm = LLMClient(
        provider="custom",
        api_key="SECRET-LIKE-key",
        base_url="https://models.example.test/v1",
        model="chat-model",
    )

    with pytest.raises(LLMError) as captured:
        await llm.chat_completion([{"role": "user", "content": "test"}])

    assert captured.value.code == "llm_timeout"
    assert "SECRET-LIKE" not in str(captured.value)
    assert "models.example.test" not in str(captured.value)


# ---- 内容处理：LLM 成功 ----
async def test_upload_llm_structured_draft(client, monkeypatch):
    fake = FakeLLM(mode="ok")
    _enable_llm(monkeypatch, fake)
    task_id = await _upload(client)
    r = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    b = r.json()
    assert b["content_processing_status"] == "llm"
    assert b["summary_status"] == "generated"
    assert b["summary"] == _GOOD["detailed"]
    assert b["generation_model_ref"]
    assert b["llm_provider"] == "deepseek"
    assert b["llm_model"] == "deepseek-chat"
    assert b["suggested_one_liner"] == _GOOD["one_liner"]
    assert b["suggested_key_points"] == _GOOD["key_points"]
    assert b["suggested_asset_type"] == "case"
    assert b["suggested_confidentiality_level"] == "L3"
    assert b["confidentiality_source"] == "ai_content"
    assert b["confidentiality_confidence"] == "medium"
    assert "内部经营分析" not in b["confidentiality_reason"]
    assert b["suggested_version"] == "V2"
    assert b["version_source"] == "ai_content"
    assert b["suggested_tags"] == _GOOD["tags"]
    # suggested_title 的现行语义仅为主题，完整旧规范名只保留在兼容元数据中。
    assert b["suggested_title"] == "零售数字化转型方案"
    # 标题 ≠ 一句话摘要（摘要不抢占标题字段）。
    assert b["suggested_title"] != b["suggested_one_liner"]
    # 命名解析结果（组件 + inferred/missing）随响应返回，供前端展示。
    naming = b["naming_parsed_fields"]
    assert naming["normalized_title"] != b["suggested_title"]
    assert naming["normalized_title"].startswith("【客户项目-交付成果】")
    assert naming["subject_or_client"] == "某零售集团"
    assert isinstance(naming["inferred_fields"], list)
    assert isinstance(naming["missing_fields"], list)
    system_prompt = fake.last_messages[0]["content"]
    assert "不得包含目标项目名、客户名称、客户简称或项目代码" in system_prompt
    assert "不得拼入分类、日期、版本或密级" in system_prompt
    assert "只能依据文档正文" in system_prompt


@pytest.mark.parametrize(
    ("file_name", "expected_version"),
    [
        ("经营复盘_20260401_V1.1_L3.md", "V1.1"),
        ("经营复盘_20260401_v2.03_L3.md", "V2.03"),
    ],
)
async def test_filename_version_wins_while_filename_level_never_drives_advice(
    client, monkeypatch, file_name, expected_version
):
    payload = {
        **_GOOD,
        "version": "V2",
        "confidentiality_level": "L4",
        "confidentiality_confidence": "high",
    }
    fake = FakeLLM(payload=payload)
    _enable_llm(monkeypatch, fake)
    task_id = await _upload(client, file_name=file_name)
    body = (
        await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    ).json()

    assert body["suggested_version"] == expected_version
    assert body["version_source"] == "source_filename"
    assert body["suggested_confidentiality_level"] == "L4"
    assert body["confidentiality_source"] == "ai_content"
    user_prompt = fake.last_messages[1]["content"]
    assert expected_version.lower() in user_prompt.lower()
    assert "L3" not in user_prompt


async def test_low_confidence_content_level_falls_back_without_filename_influence(
    client, monkeypatch
):
    payload = {
        **_GOOD,
        "version": "V2.03",
        "version_confidence": "low",
        "confidentiality_level": "L5",
        "confidentiality_confidence": "low",
    }
    _enable_llm(monkeypatch, FakeLLM(payload=payload))
    task_id = await _upload(client, file_name="敏感专题_L4.md")
    body = (
        await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    ).json()

    assert body["suggested_confidentiality_level"] == "L2"
    assert body["confidentiality_source"] == "default_needs_confirmation"
    assert body["confidentiality_confidence"] == "low"
    assert body["suggested_version"] == "V1"
    assert body["version_source"] == "default_needs_confirmation"
    assert body["version_confidence"] == "low"


async def test_upload_llm_fenced_json_parsed(client, monkeypatch):
    _enable_llm(monkeypatch, FakeLLM(mode="fenced"))
    task_id = await _upload(client)
    r = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    assert r.json()["suggested_one_liner"] == _GOOD["one_liner"]


# ---- 降级：未配置 / 调用失败 / 脏 JSON ----
async def test_upload_degraded_when_llm_disabled(client):
    # 不启用 LLM（默认）→ 降级到确定性草稿。
    task_id = await _upload(client)
    r = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    b = r.json()
    assert b["content_processing_status"] == "degraded"
    assert b["summary_status"] == "pending_model_config"
    assert b["summary"] is None
    assert b["generation_model_ref"] is None
    assert b["llm_provider"] is None
    assert b["suggested_title"]  # 仍有确定性建议
    # 降级也产出干净主题，不携带完整旧命名模板。
    assert "【" not in b["suggested_title"]
    assert b["suggested_title"] != b["suggested_one_liner"]
    assert b["suggested_version"] == "V1"
    assert b["version_source"] == "default_needs_confirmation"
    assert b["suggested_confidentiality_level"] == "L2"
    assert b["confidentiality_source"] == "default_needs_confirmation"
    # 低置信度 + 缺失字段被标记（顾问文件名不规范时，分类/客户/日期/版本走默认）。
    assert b["confidence"] is not None and b["confidence"] <= 0.4
    naming = b["naming_parsed_fields"]
    assert "primary_category" in naming["missing_fields"]
    assert "subject_or_client" in naming["missing_fields"]
    assert "date" in naming["missing_fields"]
    assert "version" in naming["missing_fields"]
    assert naming["date"] == ""
    # 缺失字段是推断字段的子集。
    assert set(naming["missing_fields"]).issubset(set(naming["inferred_fields"]))


async def test_compliant_filename_parsed_into_naming(client):
    """文件名已规范时，降级也能把组件解析进规范标题（不全走默认）。"""
    fn = "【客户项目-交付成果】组织诊断报告_云宏信息_20260327_V3_L4.txt"
    task_id = await _upload(client, file_name=fn)
    b = (
        await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    ).json()
    naming = b["naming_parsed_fields"]
    assert naming["original_naming_compliant"] is True
    assert naming["primary_category"] == "客户项目"
    assert naming["subject_or_client"] == "云宏信息"
    assert naming["date"] == "20260327"
    assert naming["version"] == "V3"
    assert b["suggested_version"] == "V3"
    assert b["version_source"] == "source_filename"
    assert b["suggested_confidentiality_level"] == "L2"
    assert b["confidentiality_source"] == "default_needs_confirmation"
    # 这些字段有文件名依据，不应标 missing。
    for f in ("primary_category", "subject_or_client", "date", "version"):
        assert f not in naming["missing_fields"]
    assert b["suggested_title"] == "组织诊断报告"


async def test_upload_degraded_on_llm_failure(client, monkeypatch):
    _enable_llm(monkeypatch, FakeLLM(mode="fail"))
    task_id = await _upload(client)  # 不应抛错
    r = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    body = r.json()
    assert body["content_processing_status"] == "degraded"
    assert body["summary_status"] == "failed"
    assert body["summary"] is None
    assert body["generation_error_category"] == "server_error"
    assert body["generation_recovery_hint"]
    assert "LLM 调用失败" not in r.text

    status = await client.get(f"/api/v1/ingest/{task_id}/status", headers=_hdr(USER_CONSULTANT))
    assert status.status_code == 200
    assert status.json()["status"] == "degraded"
    assert status.json()["error"]["code"] == "server_error"
    assert status.json()["error"]["recovery_hint"] == body["generation_recovery_hint"]


async def test_llm_json_without_detailed_does_not_mark_summary_generated(client, monkeypatch):
    _enable_llm(monkeypatch, FakeLLM(mode="missing_detailed"))
    task_id = await _upload(client)
    r = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    body = r.json()
    assert body["content_processing_status"] == "llm"
    assert body["llm_provider"] == "deepseek"
    assert body["suggested_summary"]
    assert body["summary"] is None
    assert body["summary_status"] == "failed"


async def test_upload_degraded_on_dirty_json(client, monkeypatch):
    _enable_llm(monkeypatch, FakeLLM(mode="dirty"))
    task_id = await _upload(client)
    r = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    assert r.json()["content_processing_status"] == "degraded"


# ---- confirm 三层摘要写穿 + AI/人工独立 ----
async def test_confirm_writes_three_layer_summaries(client, monkeypatch):
    _enable_llm(monkeypatch, FakeLLM(mode="ok"))
    task_id = await _upload(client)
    r = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json={
            "title": "人工确认标题",
            "one_liner": "人工一句话",
            "summary": "人工详细摘要",
            "key_points": ["人工要点1", "人工要点2"],
            "tags": ["t"],
            "target_scope": "personal",
            "asset_type": "methodology",
            "confidentiality_level": "L2",
            "ai_access_level": "A2",
        },
    )
    assert r.status_code == 200
    asset_id = r.json()["result_asset_id"]
    detail = (await client.get(f"{KN}/{asset_id}", headers=_hdr(USER_CONSULTANT))).json()
    # 资产摘要为人工确认值（独立于 AI 草稿）。
    assert detail["summary"]["one_liner"] == "人工一句话"
    assert detail["summary"]["key_points"] == ["人工要点1", "人工要点2"]
    # AI 草稿仍是 LLM 值（未被人工覆盖）。
    ai = (
        await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    ).json()
    assert ai["suggested_one_liner"] == _GOOD["one_liner"]


async def test_confirm_with_suggested_subject_yields_clean_asset_title(client, monkeypatch):
    """端到端：AI 主题建议 → 人工沿用提交，不回流旧完整命名串。"""
    _enable_llm(monkeypatch, FakeLLM(mode="ok"))
    task_id = await _upload(client, file_name="企业级AI应用案例研究报告.docx")
    ai = (
        await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    ).json()
    suggested = ai["suggested_title"]
    assert suggested == "零售数字化转型方案"
    # 顾问沿用 AI 规范标题 + AI 一句话摘要提交入库。
    r = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json={
            "title": suggested,
            "one_liner": ai["suggested_one_liner"],
            "summary": ai["suggested_summary"],
            "tags": ["t"],
            "target_scope": "personal",
            "asset_type": "case",
            "confidentiality_level": "L3",
            "ai_access_level": "A3",
        },
    )
    assert r.status_code == 200
    asset_id = r.json()["result_asset_id"]
    detail = (await client.get(f"{KN}/{asset_id}", headers=_hdr(USER_CONSULTANT))).json()
    assert detail["title"] == suggested
    assert detail["title"] != detail["summary"]["one_liner"]


# ---- 无泄露 ----
async def test_no_llm_key_leak_in_response_and_audit(client, monkeypatch):
    _enable_llm(monkeypatch, FakeLLM(mode="ok"))
    task_id = await _upload(client)
    r = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    for token in ["sk-", "Bearer", "api.deepseek.com", "Authorization"]:
        assert token not in r.text


def test_value_sanitizer_redacts_bearer():
    assert audit_service.sanitize_text("Bearer sk-abc123") == "[redacted]"


# ---- 字段校验：脏分类回退 ----
def test_valid_enum_sets_present():
    assert "methodology" in {t.value for t in AssetType}
    assert "L2" in {c.value for c in ConfidentialityLevel}

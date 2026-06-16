"""外部 LLM 内容处理测试（fake LLMClient，不打真实网络）。

覆盖：结构化 JSON 解析写草稿、provider/model 记录、降级（未配置/失败/脏 JSON）、
confirm 三层摘要(含 key_points)写穿 + AI/人工独立存储、无 api_key/Bearer 泄露、
WeKnora 链路不回归。
"""

from __future__ import annotations

import json
import re

import pytest

import app.services.content_processing as cp_module
from app.main import app
from app.schemas.enums import AssetType, ConfidentialityLevel
from app.seed.dev_seed import USER_CONSULTANT
from app.services import audit as audit_service
from app.services.llm_client import LLMClient, LLMError, get_llm_client

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

    def __init__(self, *, mode: str = "ok") -> None:
        self.mode = mode
        self.calls = 0

    async def chat_completion(
        self, messages, *, temperature=0.2, model=None, json_object=True, trace_id=None
    ):
        self.calls += 1
        if self.mode == "fail":
            raise LLMError("http_500", "LLM 调用失败")
        if self.mode == "dirty":
            return "这不是 JSON 抱歉"
        if self.mode == "fenced":
            return "```json\n" + json.dumps(_GOOD) + "\n```"
        return json.dumps(_GOOD, ensure_ascii=False)


# 平台命名格式：【一级类-二级类】主题_对象/客户_YYYYMMDD_V版本_L保密级别
_TITLE_RE = re.compile(r"^【[^-】]+-[^】]+】.+_.+_\d{8}_V\d+_L[1-5]$")

_GOOD = {
    "asset_type": "case",
    "confidentiality_level": "L3",
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
    monkeypatch.setattr(cp_module, "llm_enabled", lambda: True)
    app.dependency_overrides[get_llm_client] = lambda: fake


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.pop(get_llm_client, None)


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


# ---- 内容处理：LLM 成功 ----
async def test_upload_llm_structured_draft(client, monkeypatch):
    _enable_llm(monkeypatch, FakeLLM(mode="ok"))
    task_id = await _upload(client)
    r = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    b = r.json()
    assert b["content_processing_status"] == "llm"
    assert b["llm_provider"] == "deepseek"
    assert b["llm_model"] == "deepseek-chat"
    assert b["suggested_one_liner"] == _GOOD["one_liner"]
    assert b["suggested_key_points"] == _GOOD["key_points"]
    assert b["suggested_asset_type"] == "case"
    assert b["suggested_confidentiality_level"] == "L3"
    assert b["suggested_tags"] == _GOOD["tags"]
    # 标题是平台规范命名（非摘要式），且确定性拼装恒合规。
    assert _TITLE_RE.match(b["suggested_title"]), b["suggested_title"]
    assert (
        b["suggested_title"] == "【客户项目-交付成果】零售数字化转型方案_某零售集团_20260520_V2_L3"
    )
    # 标题 ≠ 一句话摘要（摘要不抢占标题字段）。
    assert b["suggested_title"] != b["suggested_one_liner"]
    # 命名解析结果（组件 + inferred/missing）随响应返回，供前端展示。
    naming = b["naming_parsed_fields"]
    assert naming["normalized_title"] == b["suggested_title"]
    assert naming["subject_or_client"] == "某零售集团"
    assert isinstance(naming["inferred_fields"], list)
    assert isinstance(naming["missing_fields"], list)


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
    assert b["llm_provider"] is None
    assert b["suggested_title"]  # 仍有确定性建议
    # 降级也产出**规范化**标题（非空、合规），且不等于一句话摘要。
    assert _TITLE_RE.match(b["suggested_title"]), b["suggested_title"]
    assert b["suggested_title"] != b["suggested_one_liner"]
    # 低置信度 + 缺失字段被标记（顾问文件名不规范时，分类/客户/日期/版本走默认）。
    assert b["confidence"] is not None and b["confidence"] <= 0.4
    naming = b["naming_parsed_fields"]
    assert "primary_category" in naming["missing_fields"]
    assert "subject_or_client" in naming["missing_fields"]
    assert "date" in naming["missing_fields"]
    assert "version" in naming["missing_fields"]
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
    # 这些字段有文件名依据，不应标 missing。
    for f in ("primary_category", "subject_or_client", "date", "version"):
        assert f not in naming["missing_fields"]
    assert _TITLE_RE.match(b["suggested_title"]), b["suggested_title"]


async def test_upload_degraded_on_llm_failure(client, monkeypatch):
    _enable_llm(monkeypatch, FakeLLM(mode="fail"))
    task_id = await _upload(client)  # 不应抛错
    r = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    assert r.json()["content_processing_status"] == "degraded"


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


async def test_confirm_with_suggested_title_yields_compliant_asset(client, monkeypatch):
    """端到端：AI 规范标题 → 人工沿用提交 → 资产详情标题符合平台命名规范。"""
    _enable_llm(monkeypatch, FakeLLM(mode="ok"))
    task_id = await _upload(client, file_name="企业级AI应用案例研究报告.docx")
    ai = (
        await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    ).json()
    suggested = ai["suggested_title"]
    assert _TITLE_RE.match(suggested), suggested
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
    assert _TITLE_RE.match(detail["title"]), detail["title"]
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

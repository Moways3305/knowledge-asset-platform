"""PBC-13 入库前置实体级规则脱敏测试。

覆盖：
- RuleBasedDesensitizer 各实体类别替换 + counts；普通文本不过度替换；
- content_processing 调平台侧 LLM 前用脱敏文本（fake LLM 收不到原始邮箱/手机号/身份证/
  金额/客户名）；LLM 未配置时仍记录脱敏状态；脱敏失败时平台侧 LLM 不接触原文（降级）；
- 上传/确认后 WeKnora fake 仍按信任边界收到原始文件内容，且响应/审计不泄露 WeKnora 内部
  id/ref；retry-index 不因脱敏文本缺失而被阻断；
- 上传 AI 结果只返回安全脱敏元数据（状态 + 类别计数 + 文案），不含脱敏前/后正文；审计 no-leak。
"""

from __future__ import annotations

import json

import pytest

import app.services.content_processing as cp_module
from app.main import app
from app.models.ingest import IngestTaskAiResult
from app.services.content_processing import process_content
from app.services.desensitization import (
    NullDesensitizer,
    RuleBasedDesensitizer,
    get_desensitizer,
)
from app.services.extraction import ExtractionResult
from app.services.llm_client import LLMError, get_llm_client
from app.services.weknora_client import WeKnoraError, get_weknora_client
from app.seed.dev_seed import USER_CONSULTANT

UPLOAD = "/api/v1/ingest/upload"
KN = "/api/v1/knowledge"

# 含多类敏感实体的样本（测试构造，允许出现原值）。
_SENSITIVE = (
    "联系人：张三 电话 13800138000\n"
    "邮箱 zhangsan@example.com\n"
    "身份证 110101199003078515\n"
    "银行卡 6222021234567890123\n"
    "客户：华润万家\n"
    "合同金额 ¥1,234,567.89，预算 80万元\n"
    "固话 010-12345678\n"
).encode("utf-8")

# 用于断言"平台侧 LLM 收不到原值"的原始敏感片段。
_RAW_TOKENS = [
    "13800138000",
    "zhangsan@example.com",
    "110101199003078515",
    "6222021234567890123",
    "华润万家",
    "1,234,567.89",
    "张三",
]


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


# ---------------------------------------------------------------------------
# RuleBasedDesensitizer 单测
# ---------------------------------------------------------------------------
def test_rule_desensitizer_covers_all_entity_types():
    res = RuleBasedDesensitizer().desensitize(_SENSITIVE.decode("utf-8"))
    assert res.status == "applied"
    # 各实体类别均命中并计数。
    for cat in ("email", "phone", "id_card", "bank_card", "amount", "contact", "customer", "landline"):
        assert res.counts.get(cat, 0) >= 1, (cat, res.counts)
    # 金额两处（¥... 与 80万元）。
    assert res.counts["amount"] >= 2
    # 占位符已写入，原值已被擦洗。
    for token in _RAW_TOKENS:
        if token == "张三":
            continue  # 联系人值被擦洗（见下）
        assert token not in res.text, token
    assert "【邮箱】" in res.text
    assert "【手机号】" in res.text
    assert "【身份证号】" in res.text
    assert "【银行卡号】" in res.text
    assert "【金额】" in res.text
    assert "【固话】" in res.text
    # 联系人 / 客户字段保留标签，仅擦洗值。
    assert "联系人：【联系人】" in res.text
    assert "客户：【客户】" in res.text
    assert "张三" not in res.text
    assert "华润万家" not in res.text


def test_rule_desensitizer_does_not_over_replace_plain_text():
    plain = "我们在2024年完成了三个项目交付，团队共12人参与，效果良好。第3章介绍方法论。"
    res = RuleBasedDesensitizer().desensitize(plain)
    assert res.status == "unchanged"
    assert res.counts == {}
    assert res.text == plain


def test_rule_desensitizer_empty_is_skipped():
    res = RuleBasedDesensitizer().desensitize("   ")
    assert res.status == "skipped"
    assert res.counts == {}


def test_counts_record_no_raw_values():
    res = RuleBasedDesensitizer().desensitize(_SENSITIVE.decode("utf-8"))
    serialized = json.dumps(res.counts, ensure_ascii=False)
    for token in _RAW_TOKENS:
        assert token not in serialized


def test_get_desensitizer_defaults_to_rule_based():
    assert isinstance(get_desensitizer(), RuleBasedDesensitizer)


# ---------------------------------------------------------------------------
# content_processing：平台侧 LLM 收到的是脱敏文本
# ---------------------------------------------------------------------------
class CapturingLLM:
    """记录收到的 user 内容，便于断言平台侧 LLM 不接触原文。"""

    provider = "deepseek"
    model = "deepseek-chat"

    def __init__(self, *, mode: str = "ok") -> None:
        self.mode = mode
        self.calls = 0
        self.last_user = None

    async def chat_completion(self, messages, *, temperature=0.2, model=None, json_object=True, trace_id=None):
        self.calls += 1
        self.last_user = "\n".join(m["content"] for m in messages if m["role"] == "user")
        if self.mode == "fail":
            raise LLMError("http_500", "boom")
        return json.dumps({
            "one_liner": "一句话", "detailed": "详细摘要", "key_points": ["a"], "tags": ["t"],
            "asset_type": "case", "confidentiality_level": "L3", "ai_access_level": "A3",
            "topic": "脱敏样本", "subject_or_client": "通用",
        }, ensure_ascii=False)


def _extraction(text: str) -> ExtractionResult:
    return ExtractionResult(text=text, status="extracted", error_type=None, error_message=None, char_count=len(text))


async def test_platform_llm_receives_desensitized_text(monkeypatch):
    monkeypatch.setattr(cp_module, "llm_enabled", lambda: True)
    fake = CapturingLLM()
    draft, meta = await process_content(
        fake, RuleBasedDesensitizer(),
        extraction=_extraction(_SENSITIVE.decode("utf-8")), file_name="s.txt", trace_id="t",
    )
    assert fake.calls == 1
    assert meta["status"] == "llm"
    assert meta["desensitization_status"] == "applied"
    # 平台侧 LLM 收到的是脱敏后文本：不含任何原始敏感片段。
    for token in _RAW_TOKENS:
        assert token not in fake.last_user, token
    assert "【邮箱】" in fake.last_user
    assert "【手机号】" in fake.last_user


async def test_llm_not_configured_still_records_desensitization(monkeypatch):
    monkeypatch.setattr(cp_module, "llm_enabled", lambda: False)
    fake = CapturingLLM()
    draft, meta = await process_content(
        fake, RuleBasedDesensitizer(),
        extraction=_extraction(_SENSITIVE.decode("utf-8")), file_name="s.txt", trace_id="t",
    )
    # 未配置 LLM → 不调用，但脱敏状态/计数仍记录。
    assert fake.calls == 0
    assert meta["status"] == "degraded"
    assert meta["desensitization_status"] == "applied"
    assert draft["desensitization_status"] == "applied"
    assert draft["desensitization_counts"]["email"] >= 1


async def test_desensitization_failure_skips_platform_llm(monkeypatch):
    """脱敏失败（无可用脱敏文本）→ 平台侧 LLM 不接触原文（降级）。高敏资产同此路径。"""
    monkeypatch.setattr(cp_module, "llm_enabled", lambda: True)

    class BoomDesensitizer:
        def desensitize(self, text):
            raise RuntimeError("boom")

    fake = CapturingLLM()
    draft, meta = await process_content(
        fake, BoomDesensitizer(),
        extraction=_extraction(_SENSITIVE.decode("utf-8")), file_name="s.txt", trace_id="t",
    )
    assert fake.calls == 0  # 平台侧 LLM 未接触原文
    assert meta["status"] == "degraded"
    assert meta["reason"] == "desensitization_failed"
    assert draft["desensitization_status"] == "failed"
    assert draft["desensitization_error_code"] == "desensitization_error"


async def test_non_text_extraction_skips_desensitization(monkeypatch):
    monkeypatch.setattr(cp_module, "llm_enabled", lambda: True)
    fake = CapturingLLM()
    ext = ExtractionResult(text="", status="empty", error_type="empty", error_message="无文本", char_count=0)
    draft, meta = await process_content(fake, RuleBasedDesensitizer(), extraction=ext, file_name="x.pdf", trace_id="t")
    assert fake.calls == 0
    assert meta["status"] == "degraded"
    assert draft["desensitization_status"] == "skipped"


# ---------------------------------------------------------------------------
# API：上传 AI 结果只返回安全脱敏元数据
# ---------------------------------------------------------------------------
def _enable_llm(monkeypatch, fake):
    monkeypatch.setattr(cp_module, "llm_enabled", lambda: True)
    app.dependency_overrides[get_llm_client] = lambda: fake


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.pop(get_llm_client, None)
    app.dependency_overrides.pop(get_weknora_client, None)


async def _upload(client, content=_SENSITIVE, file_name="s.txt"):
    r = await client.post(UPLOAD, headers=_hdr(USER_CONSULTANT), files={"file": (file_name, content, "text/plain")})
    return r.json()["ingest_task_id"]


async def test_ai_result_exposes_safe_desensitization_metadata_only(client, monkeypatch):
    _enable_llm(monkeypatch, CapturingLLM())
    task_id = await _upload(client)
    r = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    b = r.json()
    assert b["desensitization_status"] == "applied"
    assert b["desensitization_counts"]["email"] >= 1
    assert b["desensitization_message"]
    # 安全：不返回脱敏文本 ref、原始文件存储 ref、脱敏全文。
    # 注：extracted_text_preview 是 IMPLEMENT-14 既有"创建人查看自己上传的原文预览"
    #（原文层授权，仅完整视图返回），不属于本任务新增泄露，故单独从计数/文案维度断言。
    for token in ["desensitized_text_ref", "source_file_ref", "storage_ref", "weknora_kb_id", "weknora_doc_id"]:
        assert token not in r.text, token
    # 脱敏元数据本身（状态 + 计数 + 文案）不含任何原值。
    meta_blob = json.dumps(
        {
            "status": b["desensitization_status"],
            "counts": b["desensitization_counts"],
            "message": b["desensitization_message"],
        },
        ensure_ascii=False,
    )
    for token in _RAW_TOKENS:
        assert token not in meta_blob, token


async def test_l2_ingest_still_works_with_desensitization(client, monkeypatch):
    """L1/L2 兼容：含敏感实体也能正常走到 pending_confirmation。"""
    _enable_llm(monkeypatch, CapturingLLM())
    task_id = await _upload(client)
    b = (await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))).json()
    assert b["status"] == "pending_confirmation"
    assert b["desensitization_status"] == "applied"


# ---------------------------------------------------------------------------
# WeKnora 信任边界：底座仍收原文；retry-index 不依赖脱敏文本
# ---------------------------------------------------------------------------
class FakeWK:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.uploaded_content: bytes | None = None
        self._kb = 0
        self._doc = 0

    async def create_kb(self, *, name, embedding_model_id, trace_id=None, **_):
        self._kb += 1
        return f"kb-{self._kb}"

    async def initialize_kb(self, kb_id, **_):
        return None

    async def get_initialization_config(self, kb_id, *, trace_id=None):
        return {}

    async def upload_file(self, *, kb_id, content, file_name, mime, metadata=None, channel=None, trace_id=None):
        if self.fail:
            raise WeKnoraError("weknora_down", "底座不可用")
        self.uploaded_content = content
        self._doc += 1
        return {"id": f"doc-{self._doc}", "parse_status": "processing", "file_hash": "h"}

    async def get_knowledge(self, knowledge_id, *, trace_id=None):
        return {"id": knowledge_id, "parse_status": "completed"}

    async def delete_knowledge(self, knowledge_id, *, trace_id=None):
        return None

    async def search(self, **_):
        return []

    async def hybrid_search(self, **_):
        return []


def _enable_weknora(monkeypatch, fake, *, embedding="test-embed"):
    from app.core.config import get_settings

    monkeypatch.setattr("app.services.ingest.weknora_enabled", lambda: True)
    monkeypatch.setattr("app.services.knowledge.weknora_enabled", lambda: True)
    monkeypatch.setattr(get_settings(), "weknora_embedding_model_id", embedding)
    app.dependency_overrides[get_weknora_client] = lambda: fake


async def _confirm(client, task_id, **over):
    payload = {
        "title": "脱敏边界资产", "summary": "摘要", "tags": ["t"],
        "target_scope": "personal", "asset_type": "methodology",
        "confidentiality_level": "L2", "ai_access_level": "A2",
    }
    payload.update(over)
    return await client.post(f"/api/v1/ingest/{task_id}/confirm", headers=_hdr(USER_CONSULTANT), json=payload)


async def test_weknora_receives_original_and_no_leak(client, monkeypatch):
    ok = FakeWK()
    _enable_weknora(monkeypatch, ok)
    task_id = await _upload(client)
    r = await _confirm(client, task_id)
    assert r.status_code == 200, r.text
    assert r.json()["index_status"] == "indexed"
    # WeKnora 底座按信任边界收到**原始**文件内容（未脱敏），证明原文链路未被改写。
    assert ok.uploaded_content == _SENSITIVE
    # 但响应不泄露 WeKnora 内部 id / 存储 ref。
    for token in ["weknora_kb_id", "weknora_doc_id", "kb-", "doc-", "source_file_ref", "storage_ref"]:
        assert token not in r.text, token


async def test_retry_index_not_blocked_by_missing_desensitized_text(client, db_session, monkeypatch):
    """retry-index 重新从原始文件索引，不依赖脱敏文本（PBC-11C 语义不回归）。"""
    _enable_weknora(monkeypatch, FakeWK(fail=True))
    task_id = await _upload(client)
    r = await _confirm(client, task_id)
    assert r.json()["index_status"] == "index_failed"
    asset_id = r.json()["result_asset_id"]
    # 切换为成功底座重试。
    ok = FakeWK()
    app.dependency_overrides[get_weknora_client] = lambda: ok
    rr = await client.post(f"{KN}/{asset_id}/retry-index", headers=_hdr(USER_CONSULTANT))
    assert rr.status_code == 200, rr.text
    assert rr.json()["index_status"] == "indexed"
    # 重试同样把**原始**文件内容推给底座（不依赖任何脱敏代理）。
    assert ok.uploaded_content == _SENSITIVE


# ---------------------------------------------------------------------------
# 审计 no-leak：只记状态 + counts，不记脱敏文本 / 原值
# ---------------------------------------------------------------------------
async def test_audit_records_status_and_counts_no_raw(client, db_session, monkeypatch):
    from app.models.audit import AuditEvent
    from sqlalchemy import select

    _enable_llm(monkeypatch, CapturingLLM())
    task_id = await _upload(client)
    # ai_extracted 审计应含 desensitization_status / counts，不含原值。
    logs = (await db_session.execute(select(AuditEvent))).scalars().all()
    extracted = [lg for lg in logs if lg.action == "ingest.ai_extracted"]
    assert extracted, "应有 ingest.ai_extracted 审计"
    extra = extracted[0].extra or {}
    assert extra.get("desensitization_status") == "applied"
    assert isinstance(extra.get("desensitization_counts"), dict)
    blob = json.dumps([lg.extra for lg in logs], ensure_ascii=False)
    for token in _RAW_TOKENS:
        assert token not in blob, token


def test_null_desensitizer_passthrough_for_tests():
    res = NullDesensitizer().desensitize("含 13800138000 的文本")
    assert res.status == "unchanged"
    assert res.text == "含 13800138000 的文本"
    assert res.counts == {}

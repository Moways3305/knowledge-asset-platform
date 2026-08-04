"""内容处理服务（含命名规范化）——对抽取文本真调外部 LLM 出结构化建议草稿。

取代 的确定性 `_build_ai_result`：上传期对 `extracted_text` 调 LLM 输出
{内容密级 + **规范命名组件** + 三层摘要
(one_liner/detailed/key_points) + tags}，写 `ingest_task_ai_results` 草稿（建议层），
供 `/upload` 人工校正。

建议主题契约：
- `suggested_title` 仅表示可编辑的主题，不包含分类、对象/客户、日期、版本或密级。
- `suggested_one_liner` 仍是一句话自然语言摘要（可为整句），**不抢占标题字段**。
- LLM 只输出命名**组件**，规范标题由后端确定性拼装（保证格式恒合规）。
- 缺失字段用安全默认（客户→通用、版本→V1、分类→待分类；日期保持空缺），并在
  `naming_parsed_fields.inferred_fields` / `.missing_fields` 标注，供前端打"AI 推断 /
  待人工校正"标记。
- 原始文件名仅作来源追溯（`naming_parsed_fields.source_file_name`），不强求顾问命名合规。

强约束：
- LLM 是 **advisory**——未配置 / 调用失败 / JSON 解析失败一律**降级**到确定性最小草稿，
  **绝不让上传失败**（文件已落盘）。降级原因记审计安全元数据。
- 入库建议不再做前置脱敏：平台侧外部 API 视为受信处理方，内容建议阶段直接使用
  **抽取文本截断**作为输入（前置脱敏会削弱对客户/项目/金额/合同等上下文的理解，拉低
  命名与摘要质量）。规则脱敏引擎（`DesensitizationEngine`）暂作备用保留，待本地大模型
  资源到位后可重新接入，**当前不参与入库链路**，因此不再因"脱敏失败"阻断 LLM。
  入库阶段记 `desensitization_status = not_applicable`、`desensitization_counts = null`。
  **对外输出脱敏不变**：搜索原文 chunk / Agent 引用等仍在权限放行后做输出脱敏。
- 输出只写"建议层"；人工确认值独立存储（confirm 写 summaries / tags），不互相覆盖。
- 标题恒非空；响应/日志/审计绝不含原文全文 / storage_ref / WeKnora id /
  LLM key/base_url；只记安全状态元数据（不含原值）。
"""

from __future__ import annotations

import json
import re

from app.schemas.enums import AiAccessLevel, ConfidentialityLevel
from app.services import llm_usage
from app.services.desensitization import DesensitizationEngine
from app.services.extraction import ExtractionResult
from app.services.llm_client import (
    LLMClient,
    LLMError,
    NullLLMClient,
    safe_llm_diagnostic,
)

# 建议草稿安全上限。
_MAX_KEY_POINTS = 8
_MAX_TAGS = 8
_LLM_INPUT_CHARS = 12_000  # 截断送入 LLM 的文本，控成本/时延
_LLM_MAX_OUTPUT_TOKENS = 1_200
_LLM_MAX_INPUT_CHARS = 16_000
_VALID_LEVELS = {c.value for c in ConfidentialityLevel}
_VALID_AI = {a.value for a in AiAccessLevel}

# 命名组件安全默认值（无任何信号时使用，并标记为 missing/inferred）。
_DEFAULT_PRIMARY = "待分类"
_DEFAULT_SECONDARY = "待分类"
_DEFAULT_SUBJECT = "通用"
_DEFAULT_VERSION = "V1"
_DEFAULT_LEVEL = "L2"
_DEFAULT_AI = "A2"

# 命名组件字段（用于 inferred/missing 标注与前端展示）。
_NAMING_COMPONENT_FIELDS = (
    "primary_category",
    "secondary_category",
    "topic",
    "subject_or_client",
    "date",
    "version",
)

_COMPLIANT_RE = re.compile(r"^【([^-】]+)-([^】]+)】(.+)$")
_DATE_RE = re.compile(r"20\d{6}")
_VERSION_RE = re.compile(r"[Vv][1-9]\d*(?:\.\d+)*")
_LEVEL_RE = re.compile(r"[Ll][1-5]")
_SOURCE_VERSION_RE = re.compile(r"(?<![A-Za-z0-9])([Vv][1-9]\d*(?:\.\d+)*)(?![A-Za-z0-9.])")
_LEVEL_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])[Ll][1-5](?![A-Za-z0-9])")
_VALID_ADVICE_CONFIDENCE = {"high", "medium", "low"}
_AI_CONFIDENCE_THRESHOLD = {"high", "medium"}

_SYSTEM_PROMPT = (
    "你是企业知识资产入库助手。阅读文件名与文档正文，输出**严格 JSON**（不要多余文字）。"
    "目标：生成可编辑的主题建议、受控兼容组件与摘要字段；不要生成完整文件名或规范名。"
    "topic 不得包含目标项目名、客户名称、客户简称或项目代码；不得拼入分类、日期、版本或密级。"
    "字段："
    "primary_category（一级类，简短词，如 方法论/客户项目/行业研究/内部管理）、"
    "secondary_category（二级类，简短词，如 模型工具/交付成果/案例研究）、"
    "topic（主题，<=30字的名词短语，描述这份资产是什么；**不要写成整句摘要**）、"
    "subject_or_client（对象或客户名；无法确定填 通用 或 专题）、"
    "date（文档日期，格式 YYYYMMDD；无法从文件名/正文确定则填 null）、"
    "version（版本，如 V1/V2/V1.1；无法确定则填 null）、"
    "version_confidence（high/medium/low）、version_reason（不引用正文原句的简短说明）、"
    "confidentiality_level（L1-L5，只能依据文档正文，不得依据文件名中的 L1-L5）、"
    "confidentiality_confidence（high/medium/low）、"
    "confidentiality_reason（不引用正文原句的简短说明）、"
    "inferred_fields（数组，列出上述哪些命名字段是你推断而非有明确依据的）、"
    "one_liner（一句话自然语言摘要，<=80字，可为整句）、"
    "detailed（详细摘要，<=400字）、"
    "key_points（关键知识点数组，3-6条，每条<=60字）、tags（标签数组，3-6个）。"
    "若用户消息提供 governed_category_context，还必须从 candidates 中选择 suggested_category_id；"
    "不确定时填 null，并返回 category_confidence(high/medium/low)，禁止创造类别。"
    "当 target_scope 为 pending_selection 时，按 candidates 中的 scope 分别返回 "
    "category_suggestions，例如 {project:{suggested_category_id,category_confidence}}。"
    "再次强调：topic 是名词短语，不是 one_liner；不要把摘要句子当作标题或塞进 topic。"
    "文件名只可辅助主题、日期和版本；其中任何 L1-L5 片段都不是内容密级证据。"
)


def _clean_component(value: str) -> str:
    """清洗命名组件：去掉会破坏 `【】_` 格式的字符，压缩空白，限长。"""
    s = str(value).strip()
    for ch in "【】_":
        s = s.replace(ch, "")
    s = " ".join(s.split())
    return s[:60]


def _stem(file_name: str) -> str:
    return file_name.rsplit(".", 1)[0] if "." in file_name else file_name


def _source_filename_version(file_name: str) -> str | None:
    match = _SOURCE_VERSION_RE.search(_stem(file_name))
    return match.group(1).upper() if match else None


def _filename_without_level_tokens(file_name: str) -> str:
    """Remove historical L1-L5 tokens before the combined suggestion prompt."""
    return _LEVEL_TOKEN_RE.sub("", file_name)


def _fallback_topic(file_name: str) -> str:
    """无主题信号时从文件名兜底（非"摘要式"，仅清洗分隔符）。"""
    raw = _stem(file_name).replace("——", " ").replace("-", " ").replace("_", " ")
    return _clean_component(raw) or "未命名资产"


def _parse_compliant_filename(file_name: str) -> dict:
    """文件名已是平台格式时解析出组件作为强信号；否则返回 {}。

    顾问不强求上传前命名合规——这只是"恰好已规范"时的加分信号。
    """
    stem = _stem(file_name)
    m = _COMPLIANT_RE.match(stem)
    if not m:
        return {}
    primary, secondary, rest = m.group(1).strip(), m.group(2).strip(), m.group(3)
    parts = [p for p in rest.split("_") if p]
    out: dict = {"primary_category": primary, "secondary_category": secondary}
    # 第一段通常是主题，第二段通常是对象/客户（若不是日期/版本/级别）。
    positional = [
        p
        for p in parts
        if not (_DATE_RE.fullmatch(p) or _VERSION_RE.fullmatch(p) or _LEVEL_RE.fullmatch(p))
    ]
    if positional:
        out["topic"] = positional[0]
    if len(positional) >= 2:
        out["subject_or_client"] = positional[1]
    for p in parts:
        if _DATE_RE.fullmatch(p):
            out["date"] = p
        elif _VERSION_RE.fullmatch(p):
            out["version"] = "V" + p.lstrip("Vv")
        elif _LEVEL_RE.fullmatch(p):
            out["confidentiality_level"] = "L" + p[1]
    return out


def _is_original_compliant(file_name: str) -> bool:
    return bool(_parse_compliant_filename(file_name))


def _build_naming(file_name: str, components: dict, level: str, ai_access: str) -> dict:
    """从候选组件（LLM / 文件名解析）确定性拼装规范标题；缺失用安全默认 + 标注。

    返回 naming dict（存入 `naming_parsed_fields`，含 normalized_title /
    inferred_fields / missing_fields），供前端展示与人工校正。
    """
    inferred: set[str] = set(
        f for f in (components.get("inferred_fields") or []) if f in _NAMING_COMPONENT_FIELDS
    )
    missing: set[str] = set()

    def _raw(field: str):
        v = components.get(field)
        if v is None:
            return None
        sv = str(v).strip()
        if not sv or sv.lower() == "null":
            return None
        return sv

    def _default(field: str, value: str) -> str:
        """无信号字段：用安全默认并标 inferred + missing。"""
        inferred.add(field)
        missing.add(field)
        return value

    # primary / secondary：无信号 → 待分类（missing + inferred）。
    rp = _raw("primary_category")
    primary = _clean_component(rp) if rp else _default("primary_category", _DEFAULT_PRIMARY)
    rs = _raw("secondary_category")
    secondary = _clean_component(rs) if rs else _default("secondary_category", _DEFAULT_SECONDARY)

    # topic：有信号则用；否则从文件名兜底（有文件名信号 → 仅 inferred，不算 missing）。
    rt = _raw("topic")
    if rt:
        topic = _clean_component(rt)
    else:
        topic = _fallback_topic(file_name)
        inferred.add("topic")

    # subject/client：无信号 → 通用（missing + inferred）。
    rsub = _raw("subject_or_client")
    subject = _clean_component(rsub) if rsub else _default("subject_or_client", _DEFAULT_SUBJECT)

    # date：仅接受 YYYYMMDD；否则保持空缺（missing + inferred），绝不回退上传日期。
    rd = _raw("date")
    if rd and _DATE_RE.fullmatch(rd):
        date = rd
    else:
        date = ""
        inferred.add("date")
        missing.add("date")

    # version：仅接受 V\d+；否则 V1（missing + inferred）。
    rv = _raw("version")
    if rv and _VERSION_RE.fullmatch(rv):
        version = "V" + rv.lstrip("Vv")
    else:
        version = _DEFAULT_VERSION
        inferred.add("version")
        missing.add("version")

    level_v = level if level in _VALID_LEVELS else _DEFAULT_LEVEL
    ai_v = ai_access if ai_access in _VALID_AI else _DEFAULT_AI

    normalized_title = f"【{primary}-{secondary}】{topic}_{subject}_{date}_{version}_{level_v}"
    return {
        "primary_category": primary,
        "secondary_category": secondary,
        "topic": topic,
        "subject_or_client": subject,
        "date": date,
        "version": version,
        "confidentiality_level": level_v,
        "ai_access_level": ai_v,
        "normalized_title": normalized_title,
        # AI 推断字段（含默认）：前端打"AI 推断"；missing 子集额外打"待人工校正"。
        "inferred_fields": sorted(inferred),
        "missing_fields": sorted(missing),
        # 来源追溯：原始文件名 + 是否本就规范（不强求）。
        "source_file_name": file_name,
        "original_naming_compliant": _is_original_compliant(file_name),
    }


def _naming_anomalies(naming: dict) -> list[str]:
    if naming["original_naming_compliant"]:
        return []
    return ["原始文件名不符合平台命名格式，已提取主题并保留兼容命名组件，请人工校正推断字段"]


def _degraded_draft(file_name: str, extraction: ExtractionResult) -> dict:
    """确定性最小草稿（LLM 不可用 / 失败时的降级）。

    仍尽量按文件名提取**主题与兼容命名组件**（能解析多少字段就解析多少），缺失用安全默认并
    标低置信度。标题恒非空、恒符合平台格式，且不等于一句话摘要。
    """
    # 文件名若已规范则作为强信号；否则空组件 → 全部走默认。
    components = _parse_compliant_filename(file_name)
    source_version = _source_filename_version(file_name)
    if source_version:
        components["version"] = source_version
    # Historical filename L1-L5 remains parse metadata only. It never chooses advice.
    naming = _build_naming(file_name, components, _DEFAULT_LEVEL, _DEFAULT_AI)
    if source_version:
        naming["inferred_fields"] = [
            field for field in naming["inferred_fields"] if field != "version"
        ]
        naming["missing_fields"] = [
            field for field in naming["missing_fields"] if field != "version"
        ]

    if extraction.status == "extracted":
        lines = [ln.strip() for ln in extraction.text.splitlines() if ln.strip()]
        one_liner = (lines[0][:80] if lines else naming["topic"]) or naming["topic"]
        detailed = " ".join(extraction.text.split())[:400] or f"已从「{file_name}」抽取文本。"
        stem = _stem(file_name)
        tags = ["待校正", stem[:20]] if stem else ["待校正"]
        confidence = 0.4
    else:
        one_liner = naming["topic"]
        detailed = (
            f"未能从文件内容抽取（{extraction.error_type or extraction.status}），请人工补全。"
        )
        tags = ["待校正", "待补全"]
        confidence = 0.2

    return {
        "suggested_title": naming["topic"],
        "suggested_one_liner": one_liner,
        "suggested_summary": detailed,  # detailed
        "suggested_key_points": [],
        "suggested_tags": tags,
        "suggested_asset_type": None,
        "suggested_version": source_version or _DEFAULT_VERSION,
        "version_source": "source_filename" if source_version else "default_needs_confirmation",
        "version_confidence": "high" if source_version else "low",
        "version_reason": (
            "从源文件名识别到标准版本" if source_version else "未能可靠判断版本，已使用规则默认值"
        ),
        "suggested_confidentiality_level": naming["confidentiality_level"],
        "confidentiality_source": "default_needs_confirmation",
        "confidentiality_confidence": "low",
        "confidentiality_reason": "AI 未能可靠判断内容密级，已使用规则默认值",
        "suggested_ai_access_level": None,
        "suggested_phase_key": None,
        "confidence": confidence,
        "naming_compliant": naming["original_naming_compliant"],
        "naming_parsed_fields": naming,
        "naming_anomalies": _naming_anomalies(naming),
        "llm_provider": None,
        "llm_model": None,
        "extracted_text": extraction.text or None,
        "extracted_char_count": extraction.char_count,
        "extraction_status": extraction.status,
        # 入库前置脱敏已退出当前链路（平台侧外部 API 视为受信处理方）：恒记
        # not_applicable，counts 置空。规则脱敏引擎保留为备用，不在此处执行。
        # 绝不含脱敏文本或原值。
        "desensitization_status": "not_applicable",
        "desensitization_counts": None,
        "desensitization_error_code": None,
    }


def _coerce_list(value, cap: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out = [str(v).strip()[:80] for v in value if str(v).strip()]
    return out[:cap]


def _parse_llm_json(content: str) -> dict:
    """稳健解析 LLM 输出 JSON（容忍 ```json 包裹 / 前后噪声）。"""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text[:4].lower() == "json":
            text = text[4:]
    # 截取首个 { 到末个 }，容忍少量噪声。
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    result: dict = json.loads(text)
    return result


async def process_content(
    llm: LLMClient | NullLLMClient,
    desensitizer: DesensitizationEngine,
    *,
    extraction: ExtractionResult,
    file_name: str,
    trace_id: str | None,
    category_context: dict | None = None,
    content_hash: str | None = None,
    target_scope: str = "unscoped",
    target_project_id: str | None = None,
) -> tuple[dict, dict]:
    """返回 (ai_result 草稿 dict, meta{status,reason,provider,model})。绝不抛出。

    `desensitizer` 暂作备用保留（参数沿用上游 DI 接线），当前入库建议链路**不调用**它：
    平台侧外部 API 视为受信处理方，内容建议直接吃抽取文本。待本地大模型资源到位后可在此
    重新接入。入库阶段恒记 `desensitization_status = not_applicable`、counts 置空。
    """
    del desensitizer  # 当前链路不做前置脱敏；保留入参以便后续重新接入
    base = _degraded_draft(file_name, extraction)

    # 无可抽取文本 → 平台侧 LLM 不接触内容（降级）。
    # （WeKnora 底座按已确认信任边界仍可索引原始文件，不在此处理。）
    if extraction.status != "extracted":
        base["naming_parsed_fields"]["generation_status"] = "failed"
        return base, {
            "status": "degraded",
            "reason": "extraction_not_text",
            "provider": None,
            "model": None,
            "desensitization_status": "not_applicable",
            "desensitization_counts": None,
        }

    # LLM 未配置 → 降级（脱敏不参与链路，无脱敏元数据需保留）。
    if isinstance(llm, NullLLMClient) or not getattr(llm, "provider", ""):
        base["naming_parsed_fields"]["generation_status"] = "pending_model_config"
        diagnostic = safe_llm_diagnostic("llm_not_configured")
        base["naming_parsed_fields"]["generation_error_category"] = diagnostic.category
        base["naming_parsed_fields"]["generation_recovery_hint"] = diagnostic.remediation_hint
        return base, {
            "status": "degraded",
            "reason": "llm_not_configured",
            "provider": None,
            "model": None,
            "desensitization_status": "not_applicable",
            "desensitization_counts": None,
        }

    # 平台侧外部 LLM 直接接收抽取文本（截断控成本/时延）——不再前置脱敏，
    # 以保留客户/项目/金额/合同等上下文，提升命名与摘要质量。
    effective_category_context = category_context
    governed_context = ""
    if effective_category_context:
        governed_context = "\ngoverned_category_context：" + json.dumps(
            effective_category_context, ensure_ascii=False
        )
    user_prefix = (
        f"文件名（已移除密级片段）：{_filename_without_level_tokens(file_name)}"
        f"{governed_context}\n文档内容：\n"
    )
    available_text_chars = _LLM_MAX_INPUT_CHARS - len(_SYSTEM_PROMPT) - len(user_prefix)
    if available_text_chars < 0 and effective_category_context is not None:
        # An unusually large rule catalog must not break content generation.
        # Classification will safely fall back to the later budget-aware path.
        effective_category_context = None
        governed_context = ""
        user_prefix = (
            f"文件名（已移除密级片段）：{_filename_without_level_tokens(file_name)}\n文档内容：\n"
        )
        available_text_chars = _LLM_MAX_INPUT_CHARS - len(_SYSTEM_PROMPT) - len(user_prefix)
    text = extraction.text[: min(_LLM_INPUT_CHARS, max(0, available_text_chars))]
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (f"{user_prefix}{text}"),
        },
    ]
    try:
        # Test and integration adapters retain the historical minimal method
        # signature; production LLMClient receives the enforced output cap.
        if isinstance(llm, LLMClient):
            raw = await llm.chat_completion(
                messages,
                max_input_chars=_LLM_MAX_INPUT_CHARS,
                max_tokens=_LLM_MAX_OUTPUT_TOKENS,
                trace_id=trace_id,
            )
        else:
            raw = await llm.chat_completion(messages, trace_id=trace_id)
        parsed = _parse_llm_json(raw)
    except (LLMError, json.JSONDecodeError, ValueError, TypeError) as exc:
        base["naming_parsed_fields"]["generation_status"] = "failed"
        diagnostic = safe_llm_diagnostic(getattr(exc, "code", None) or "llm_bad_response")
        base["naming_parsed_fields"]["generation_error_category"] = diagnostic.category
        base["naming_parsed_fields"]["generation_recovery_hint"] = diagnostic.remediation_hint
        return base, {
            "status": "degraded",
            "reason": diagnostic.category,
            "provider": None,
            "model": None,
            "desensitization_status": "not_applicable",
            "desensitization_counts": None,
        }

    # 校验 + 落值（脏字段回退默认）。
    one_liner = str(parsed.get("one_liner") or base["suggested_one_liner"])[:200]
    detailed_raw = str(parsed.get("detailed") or "").strip()
    summary_generated = bool(detailed_raw)
    detailed = (detailed_raw if summary_generated else str(base["suggested_summary"]))[:2000]
    key_points = _coerce_list(parsed.get("key_points"), _MAX_KEY_POINTS)
    tags = _coerce_list(parsed.get("tags"), _MAX_TAGS) or base["suggested_tags"]
    level = parsed.get("confidentiality_level")
    confidentiality_confidence = str(parsed.get("confidentiality_confidence") or "").lower()
    confidentiality_is_reliable = (
        level in _VALID_LEVELS and confidentiality_confidence in _AI_CONFIDENCE_THRESHOLD
    )
    level_v = str(level) if confidentiality_is_reliable else _DEFAULT_LEVEL
    ai_v = _DEFAULT_AI

    # 命名组件：优先 LLM，其次文件名解析（顾问命名合规时）作为兜底信号。
    fn_parsed = _parse_compliant_filename(file_name)
    components: dict = dict(fn_parsed)
    for field in _NAMING_COMPONENT_FIELDS:
        if field == "version":
            continue
        v = parsed.get(field)
        if v is not None and str(v).strip() and str(v).strip().lower() != "null":
            components[field] = v
    inferred_fields = set(_coerce_list(parsed.get("inferred_fields"), 12))
    source_version = _source_filename_version(file_name)
    llm_version = str(parsed.get("version") or "").strip().upper()
    llm_version_confidence = str(parsed.get("version_confidence") or "").lower()
    if source_version:
        suggested_version = source_version
        version_source = "source_filename"
        version_confidence = "high"
        version_reason = "从源文件名识别到标准版本"
        inferred_fields.discard("version")
    elif (
        _VERSION_RE.fullmatch(llm_version)
        and llm_version_confidence in _AI_CONFIDENCE_THRESHOLD
        and "version" not in inferred_fields
    ):
        suggested_version = llm_version
        version_source = "ai_content"
        version_confidence = llm_version_confidence
        version_reason = "AI 根据正文与可用元数据建议版本"
        inferred_fields.discard("version")
    else:
        suggested_version = _DEFAULT_VERSION
        version_source = "default_needs_confirmation"
        version_confidence = "low"
        version_reason = "未能可靠判断版本，已使用规则默认值"
        inferred_fields.add("version")
    components["version"] = suggested_version
    components["inferred_fields"] = sorted(inferred_fields)
    naming = _build_naming(file_name, components, level_v, ai_v)
    if version_source == "default_needs_confirmation":
        naming["missing_fields"] = sorted(set(naming["missing_fields"]) | {"version"})
        naming["inferred_fields"] = sorted(set(naming["inferred_fields"]) | {"version"})
    naming["summary_generated"] = summary_generated
    naming["generation_status"] = "generated" if summary_generated else "failed"
    if not summary_generated:
        diagnostic = safe_llm_diagnostic("llm_bad_response")
        naming["generation_error_category"] = diagnostic.category
        naming["generation_recovery_hint"] = diagnostic.remediation_hint

    if content_hash:
        naming["generation_cache_fingerprint"] = llm_usage.cache_fingerprint(
            content_hash=content_hash,
            scope=target_scope,
            project_id=target_project_id,
            rule_revision=int((effective_category_context or {}).get("rule_revision") or 0),
            provider=getattr(llm, "provider", ""),
            model=getattr(llm, "model", ""),
        )

    if effective_category_context:
        candidates = effective_category_context.get("candidates") or []
        revision = effective_category_context.get("rule_revision")
        pending_selection = effective_category_context.get("target_scope") == "pending_selection"
        raw_by_scope = parsed.get("category_suggestions") if pending_selection else None
        scopes = (
            sorted(
                {
                    str(item.get("scope"))
                    for item in candidates
                    if isinstance(item, dict) and item.get("scope")
                }
            )
            if pending_selection
            else [str(effective_category_context.get("target_scope") or "")]
        )
        suggestions: dict[str, dict] = {}
        for scope in scopes:
            scoped_candidates = [
                item
                for item in candidates
                if isinstance(item, dict) and (not pending_selection or item.get("scope") == scope)
            ]
            allowed = {str(item.get("id")) for item in scoped_candidates}
            raw_suggestion = (
                raw_by_scope.get(scope, {}) if isinstance(raw_by_scope, dict) else parsed
            )
            category_id = str(raw_suggestion.get("suggested_category_id") or "")
            category_confidence = str(raw_suggestion.get("category_confidence") or "low").lower()
            reliable = category_id in allowed and category_confidence in _AI_CONFIDENCE_THRESHOLD
            suggestion = {
                "suggested_category_id": category_id if reliable else None,
                "category_source": "ai_content" if reliable else "needs_manual",
                "category_confidence": (
                    category_confidence
                    if category_confidence in _VALID_ADVICE_CONFIDENCE
                    else "low"
                ),
                "category_reason": (
                    "AI 根据首次内容生成结果匹配当前目录规则"
                    if reliable
                    else "AI 未能可靠判断，请人工选择目录类别"
                ),
                "candidate_rule_revision": revision,
                "target_scope": scope,
                "target_project_id": (
                    None
                    if pending_selection
                    else effective_category_context.get("target_project_id")
                ),
                "status": "classified" if reliable else "needs_manual",
                "retryable": False,
                "model_ref": llm_usage.safe_model_ref(
                    getattr(llm, "provider", None), getattr(llm, "model", None)
                ),
                "candidate_fingerprint": llm_usage.candidate_fingerprint(list(allowed)),
            }
            if content_hash and isinstance(revision, int):
                suggestion["cache_fingerprint"] = llm_usage.cache_fingerprint(
                    content_hash=content_hash,
                    scope="pending_selection" if pending_selection else scope,
                    project_id=(
                        None
                        if pending_selection
                        else effective_category_context.get("target_project_id")
                    ),
                    rule_revision=revision,
                    provider=getattr(llm, "provider", ""),
                    model=getattr(llm, "model", ""),
                )
            suggestions[scope] = suggestion
        if pending_selection:
            naming["category_suggestions_by_scope"] = suggestions
        elif suggestions:
            naming["category_suggestion"] = suggestions[scopes[0]]

    draft = dict(base)
    draft.update(
        # suggested_title 的产品语义是主题；完整规范名只由已发布规则在确认时生成。
        suggested_title=naming["topic"],
        suggested_one_liner=one_liner,
        suggested_summary=detailed,
        suggested_key_points=key_points,
        suggested_tags=tags,
        suggested_asset_type=None,
        suggested_version=suggested_version,
        version_source=version_source,
        version_confidence=version_confidence,
        version_reason=version_reason,
        suggested_confidentiality_level=level_v,
        confidentiality_source=(
            "ai_content" if confidentiality_is_reliable else "default_needs_confirmation"
        ),
        confidentiality_confidence=(
            confidentiality_confidence
            if confidentiality_confidence in _VALID_ADVICE_CONFIDENCE
            else "low"
        ),
        confidentiality_reason=(
            f"AI 根据正文内容特征建议为 {level_v}"
            if confidentiality_is_reliable
            else "AI 未能可靠判断内容密级，已使用规则默认值"
        ),
        suggested_ai_access_level=None,
        naming_compliant=naming["original_naming_compliant"],
        naming_parsed_fields=naming,
        naming_anomalies=_naming_anomalies(naming),
        confidence=0.85,
        llm_provider=getattr(llm, "provider", None) or None,
        llm_model=getattr(llm, "model", None) or None,
    )
    return draft, {
        "status": "llm",
        "reason": None,
        "provider": draft["llm_provider"],
        "model": draft["llm_model"],
        "usage": (
            {
                "prompt_tokens": llm.last_usage.prompt_tokens,
                "completion_tokens": llm.last_usage.completion_tokens,
                "total_tokens": llm.last_usage.total_tokens,
            }
            if isinstance(llm, LLMClient) and llm.last_usage is not None
            else None
        ),
        "desensitization_status": "not_applicable",
        "desensitization_counts": None,
    }

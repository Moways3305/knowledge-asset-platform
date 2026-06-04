"""脱敏引擎（R2 入库前置 + R3 检索输出）。

两类脱敏，定位不同，不要混淆：

1. **入库前置脱敏 `DesensitizationEngine`（同步）**：路径 B"LLM 调用前先脱敏"的可选
   前置层。本地 Deepseek / Ollama 未就绪前用 `NullDesensitizer` 透传——**当前不做任何
   脱敏**；待 Ollama 到位在此前置实体脱敏，接口不变。

2. **检索输出脱敏 `OutputDesensitizer`（异步，R3 真实现）**：把将返回给调用方的
   WeKnora 原文 chunk 做实体擦洗（客户名/金额/联系人/个人信息）。用 R2 已就绪的外部
   LLM 实现（老板已允许外部 API 接触原文），不依赖未部署的 Ollama。

强约束（R3 头号安全闸）：
- 安全主控制是**确定性权限闸**——无权一律只给摘要卡片，**绝不**靠"脱敏后给原文"兜底
  越权；LLM 脱敏只是放行后的内容擦洗层。
- LLM 脱敏是 best-effort：不可用 / 失败时**保守降级 = 不返回原文**（`scrub` 返回 None，
  调用方据此只给卡片 + 联系人）。宁可少给，不可错给。
"""

from __future__ import annotations

from typing import Protocol

from app.services.llm_client import LLMClient, LLMError, NullLLMClient


class DesensitizationEngine(Protocol):
    def desensitize(self, text: str) -> str:  # pragma: no cover - 接口
        ...


class NullDesensitizer:
    """透传脱敏器（未配置 / 路径 A 原文入库）。"""

    def desensitize(self, text: str) -> str:
        return text


def get_desensitizer() -> DesensitizationEngine:
    """FastAPI 依赖：当前恒返回 NullDesensitizer（入库前置 Ollama 真实现挂起）。"""
    return NullDesensitizer()


class OutputDesensitizer(Protocol):
    async def scrub(self, text: str, *, trace_id: str | None = None) -> str | None:  # pragma: no cover - 接口
        ...


# 输出脱敏的系统提示：只擦洗敏感实体，保留语义，不解释、不补全。
_SCRUB_SYSTEM_PROMPT = (
    "你是企业数据脱敏器。请对给定文本中的客户/公司名称、人名、联系方式（电话/邮箱/"
    "微信）、金额与价格、合同号/身份证号等敏感实体做脱敏（用占位符如【客户】【金额】"
    "替换），**保留原文语义、结构与非敏感内容**。只输出脱敏后的文本本身，不要解释、"
    "不要添加任何前后缀。"
)


class LlmOutputDesensitizer:
    """用外部 LLM 做检索输出实体脱敏（R3 真实现）。

    `scrub` 返回脱敏后文本；LLM 不可用 / 调用失败 → 返回 **None**（保守降级，调用方
    据此不返回原文）。
    """

    def __init__(self, llm: "LLMClient | NullLLMClient") -> None:
        self._llm = llm

    async def scrub(self, text: str, *, trace_id: str | None = None) -> str | None:
        if not text or not text.strip():
            return text
        try:
            out = await self._llm.chat_completion(
                [
                    {"role": "system", "content": _SCRUB_SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                temperature=0.0,
                json_object=False,
                trace_id=trace_id,
            )
        except LLMError:
            # 保守降级：脱敏不可用时不返回任何原文内容。
            return None
        out = (out or "").strip()
        if not out:
            return None
        # Fail-closed：若 LLM 把原文原样返回（脱敏是 no-op），视同脱敏未生效 → 返回 None，
        # 不外泄未脱敏原文。比较去首尾空白后是否与输入逐字节相同（不依赖 LLM 自觉脱敏）。
        if out == text.strip():
            return None
        return out


def get_output_desensitizer(llm: "LLMClient | NullLLMClient") -> LlmOutputDesensitizer:
    """构建检索输出脱敏器（包裹注入的 LLM 客户端；未配置时其 scrub 恒降级为 None）。"""
    return LlmOutputDesensitizer(llm)

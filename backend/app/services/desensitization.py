"""脱敏引擎。

两类脱敏，定位不同，不要混淆：

1. **入库前置脱敏 `DesensitizationEngine`（同步，确定性规则）**：路径 B / 路径 A 文本
   抽取成功后、调用**平台侧外部 LLM 内容建议前**先做的实体擦洗层。起默认用
   `RuleBasedDesensitizer`（本地正则、无外部网络、无新依赖），把邮箱 / 手机号 / 固话 /
   身份证号 / 银行卡号 / 长数字账号 / 金额 / 联系人 / 客户公司字段替换为占位符。
   `desensitize()` 返回结构化 `DesensitizationResult`（脱敏文本 + 状态 + 类别计数），
   只用于平台侧 LLM 输入与安全展示元数据，**不替代原文**。

   边界（总经理确认的信任边界）：**WeKnora 底座及其 LLM 是受信任的外部/底座处理方**，
   可继续接收原始文件 / 原文内容做索引，本层不阻断 WeKnora 原文链路；规则脱敏只擦洗
   送往平台侧外部 LLM 的那一份抽取文本。原始文件仍保留在平台受控存储，供授权预览/溯源。

2. **检索输出脱敏 `OutputDesensitizer`（异步）**：把将返回给调用方的
   WeKnora 原文 chunk 做实体擦洗（客户名/金额/联系人/个人信息）。用已就绪的外部
   LLM 实现（已允许外部 API 接触原文），不依赖未部署的 Ollama。

强约束（头号安全闸）：
- 安全主控制是**确定性权限闸**——无权一律只给摘要卡片，**绝不**靠"脱敏后给原文"兜底
  越权；LLM 脱敏只是放行后的内容擦洗层。
- LLM 输出脱敏是 best-effort：不可用 / 失败时**保守降级 = 不返回原文**（`scrub` 返回 None，
  调用方据此只给卡片 + 联系人）。宁可少给，不可错给。
- 入库前置脱敏 counts 只记录类别和数量，**绝不记录原值**；脱敏文本不入任何响应 / 审计 /
  前端类型。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from app.services.llm_client import LLMClient, LLMError, NullLLMClient


@dataclass
class DesensitizationResult:
    """入库前置脱敏结果（结构化）。

    - `text`：脱敏后文本（仅用于平台侧外部 LLM 内容建议输入；失败时为空串，调用方据此不喂 LLM）。
    - `status`：applied（命中并替换）| unchanged（无命中，原样透传）| skipped（无可脱敏文本）
      | failed（脱敏过程异常）。
    - `counts`：类别 → 替换数量，**绝不含原值**。
    - `error_code`：失败时的安全错误码（无原文/无堆栈细节）。
    """

    text: str
    status: str  # applied | unchanged | skipped | failed
    counts: dict[str, int] = field(default_factory=dict)
    error_code: str | None = None


class DesensitizationEngine(Protocol):
    def desensitize(self, text: str) -> DesensitizationResult:  # pragma: no cover - 接口
        ...


class NullDesensitizer:
    """透传脱敏器（仅用于测试或显式禁用）。不替换任何内容，状态为 unchanged/skipped。"""

    def desensitize(self, text: str) -> DesensitizationResult:
        if not text or not text.strip():
            return DesensitizationResult(text=text or "", status="skipped", counts={})
        return DesensitizationResult(text=text, status="unchanged", counts={})


# ---------------------------------------------------------------------------
# 规则脱敏
# ---------------------------------------------------------------------------
# 占位符：类别 → 替换文本。counts 用同一类别 key。
_PLACEHOLDER = {
    "email": "【邮箱】",
    "id_card": "【身份证号】",
    "bank_card": "【银行卡号】",
    "phone": "【手机号】",
    "landline": "【固话】",
    "amount": "【金额】",
    "account": "【账号】",
    "contact": "【联系人】",
    "customer": "【客户】",
}

# 金额：带货币标记（¥/￥/人民币/RMB）或数字 + 中文金额单位（万/亿/元）。普通数字不替换。
_AMOUNT_RES = (
    re.compile(
        r"(?:人民币|RMB)\s*\d[\d,]*(?:\.\d+)?\s*(?:亿元|万元|千元|亿|万|元)?", re.IGNORECASE
    ),
    re.compile(r"[¥￥]\s?\d[\d,]*(?:\.\d+)?\s*(?:亿元|万元|千元|亿|万|元)?"),
    re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:亿元|万元|千元|亿元|万|亿|元)"),
)

# 联系人 / 客户公司字段：保留标签与分隔符，仅擦洗字段值。
_CONTACT_RE = re.compile(
    r"(?P<label>客户联系人|项目联系人|联系人|对接人)(?P<sep>[\s:：]+)"
    r"(?P<val>[^\s，,。；;、:：\n]{1,20})"
)
_CUSTOMER_RE = re.compile(
    r"(?P<label>客户名称|客户单位|客户|公司名称|单位名称|甲方|乙方)(?P<sep>\s*[:：]\s*)"
    r"(?P<val>[^\s，,。；;、:：\n]{2,40})"
)

# 顺序敏感：长/结构化标识先替换，避免被泛数字规则吞掉（手机号不能先被长数字账号吃掉）。
_SIMPLE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    # 邮箱
    ("email", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    # 身份证号（18 位：17 数字 + 校验位 0-9/X；或 15 位）。先于银行卡 / 手机号。
    ("id_card", re.compile(r"(?<![0-9Xx])(?:\d{17}[0-9Xx]|\d{15})(?![0-9Xx])")),
    # 银行卡号 / 长账号（16-19 连续数字）。先于手机号。
    ("bank_card", re.compile(r"(?<!\d)\d{16,19}(?!\d)")),
    # 中国大陆手机号（11 位，1[3-9] 开头）。
    ("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    # 固话（区号 + 号码，可带分隔符）。
    ("landline", re.compile(r"(?<!\d)0\d{2,3}[\-\s]?\d{7,8}(?!\d)")),
    # 其余长数字账号（12-19 位，前面规则未覆盖到的）。
    ("account", re.compile(r"(?<!\d)\d{12,19}(?!\d)")),
)


class RuleBasedDesensitizer:
    """确定性规则脱敏器。

    覆盖：邮箱、中国大陆手机号、固话、身份证号、银行卡号 / 长数字账号、金额表达、
    联系人字段、客户/公司字段。规则有序，长/结构化标识优先，避免被泛数字规则吞掉。
    counts 只记类别与数量，绝不记录原值。
    """

    def desensitize(self, text: str) -> DesensitizationResult:
        if not text or not text.strip():
            return DesensitizationResult(text=text or "", status="skipped", counts={})

        counts: dict[str, int] = {}
        out = text

        def _bump(category: str, n: int) -> None:
            if n:
                counts[category] = counts.get(category, 0) + n

        # 1) 金额（货币标记 / 中文金额单位）——先于泛数字规则，保住 ¥/万/元 表达。
        for rx in _AMOUNT_RES:
            out, n = rx.subn(_PLACEHOLDER["amount"], out)
            _bump("amount", n)

        # 2) 结构化标识（邮箱/身份证/银行卡/手机/固话/账号）按既定顺序替换。
        for category, rx in _SIMPLE_RULES:
            out, n = rx.subn(_PLACEHOLDER[category], out)
            _bump(category, n)

        # 3) 联系人字段：保留标签 + 分隔符，仅擦洗值。
        out, n = _CONTACT_RE.subn(
            lambda m: f"{m.group('label')}{m.group('sep')}{_PLACEHOLDER['contact']}", out
        )
        _bump("contact", n)

        # 4) 客户 / 公司字段：保留标签 + 分隔符，仅擦洗值。
        out, n = _CUSTOMER_RE.subn(
            lambda m: f"{m.group('label')}{m.group('sep')}{_PLACEHOLDER['customer']}", out
        )
        _bump("customer", n)

        status = "applied" if counts else "unchanged"
        return DesensitizationResult(text=out, status=status, counts=counts)


def get_desensitizer() -> DesensitizationEngine:
    """FastAPI 依赖：默认返回规则脱敏器。"""
    return RuleBasedDesensitizer()


class OutputDesensitizer(Protocol):
    async def scrub(
        self, text: str, *, trace_id: str | None = None
    ) -> str | None:  # pragma: no cover - 接口
        ...


# 输出脱敏的系统提示：只擦洗敏感实体，保留语义，不解释、不补全。
_SCRUB_SYSTEM_PROMPT = (
    "你是企业数据脱敏器。请对给定文本中的客户/公司名称、人名、联系方式（电话/邮箱/"
    "微信）、金额与价格、合同号/身份证号等敏感实体做脱敏（用占位符如【客户】【金额】"
    "替换），**保留原文语义、结构与非敏感内容**。只输出脱敏后的文本本身，不要解释、"
    "不要添加任何前后缀。"
)


class LlmOutputDesensitizer:
    """用外部 LLM 做检索输出实体脱敏。

    `scrub` 返回脱敏后文本；LLM 不可用 / 调用失败 → 返回 **None**（保守降级，调用方
    据此不返回原文）。
    """

    def __init__(self, llm: LLMClient | NullLLMClient) -> None:
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


def get_output_desensitizer(llm: LLMClient | NullLLMClient) -> LlmOutputDesensitizer:
    """构建检索输出脱敏器（包裹注入的 LLM 客户端；未配置时其 scrub 恒降级为 None）。"""
    return LlmOutputDesensitizer(llm)

"""检索意图识别（R3）。

蓝图 §6.4：6 类意图（查找 / 问答 / 生成 / 推荐 / 检查 / 总结）决定返回格式与检索范围。

实现选型：**确定性规则分类**（关键词命中），不调外部 LLM。理由——意图分类只用于
路由"返回卡片 or 附答案"，不是安全闸；规则分类零网络、可预测、易测试，且失败不会
泄露任何内容。无法判定时**降级默认"查找"（search）**（只给卡片，最保守）。

约束（系统§意图识别）：**不改写用户原始 query**——分类只读 query，路由不修改它。
调用方可用 `intent` 显式指定，跳过规则分类。
"""

from __future__ import annotations

from enum import Enum


class SearchIntent(str, Enum):
    """检索意图 6 类。"""

    search = "search"  # 查找：列出相关知识卡片
    qa = "qa"  # 问答：基于放行 chunk 自拼答案
    generate = "generate"  # 生成：基于知识起草内容
    recommend = "recommend"  # 推荐：推荐相关/可复用知识
    check = "check"  # 检查：核对/合规/审查
    summarize = "summarize"  # 总结：归纳概括


# 附答案（需要放行 chunk + LLM 自拼）的意图；其余只给卡片。
INTENTS_WITH_ANSWER: frozenset[SearchIntent] = frozenset(
    {SearchIntent.qa, SearchIntent.generate, SearchIntent.summarize, SearchIntent.check}
)

# 关键词规则（按优先级从具体到一般）。命中即归类；都不命中降级 search。
_RULES: list[tuple[SearchIntent, tuple[str, ...]]] = [
    (SearchIntent.summarize, ("总结", "概括", "归纳", "梳理", "提炼")),
    (SearchIntent.generate, ("生成", "起草", "撰写", "写一", "拟一", "帮我写", "草拟", "编写")),
    (SearchIntent.check, ("检查", "核对", "审查", "合规", "是否符合", "校验", "核查")),
    (SearchIntent.recommend, ("推荐", "有没有", "类似", "相关案例", "可复用", "借鉴")),
    (SearchIntent.qa, ("如何", "怎么", "怎样", "为什么", "什么是", "是什么", "?", "？")),
]


def classify_intent(query: str, *, explicit: str | None = None) -> SearchIntent:
    """识别检索意图。explicit 合法则直接采用；否则规则分类，降级默认 search。"""
    if explicit:
        try:
            return SearchIntent(explicit)
        except ValueError:
            pass  # 非法显式意图 → 走规则分类
    q = (query or "").lower()
    for intent, keywords in _RULES:
        if any(k in q for k in keywords):
            return intent
    return SearchIntent.search


def wants_answer(intent: SearchIntent) -> bool:
    """该意图是否需要附 LLM 自拼答案 + 引用。"""
    return intent in INTENTS_WITH_ANSWER

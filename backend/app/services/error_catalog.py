"""中央错误目录：把安全 error_code 映射为三层安全文案。

同一个底座/扫描失败，在不同人面前显示不同粒度，但**都不**泄露密钥 / 真实 model id /
kb id / doc id / 内部存储引用 / 上游原始 message / payload / URL 值：

- `user_message`：业务用户可行动文案（资产已保存 / 可重试 / 联系管理员）。
- `operator_message` + `remediation_hint`：admin/运营诊断（可含**配置项名**，不含配置值）。
- `severity`：审计 / 告警分类（info | warning | error | critical）。

**allowlist**：只按已知 code 取固定文案；未知 code 一律降级到 `unknown` 安全文案。
绝不把传入的上游 message / payload / id 拼进任何文案。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorInfo:
    user_message: str
    operator_message: str
    remediation_hint: str
    severity: str  # info | warning | error | critical


_CATALOG: dict[str, ErrorInfo] = {
    "weknora_not_configured": ErrorInfo(
        user_message="知识底座未启用，资产已保存，但暂不参与语义检索。",
        operator_message="WeKnora 知识底座未配置。",
        remediation_hint="检查 WEKNORA_BASE_URL / WEKNORA_API_KEY 是否已配置（只看项名，不含值）。",
        severity="warning",
    ),
    "weknora_embedding_model_missing": ErrorInfo(
        user_message="知识底座模型配置未完成，资产已保存，可由管理员配置后重试索引。",
        operator_message="平台默认 embedding 模型未配置（weknora_default_models），或底座嵌入模型未就绪。",
        remediation_hint="在模型配置中心设置平台默认 embedding 模型（不再依赖已废弃的 WEKNORA_EMBEDDING_MODEL_ID）后重试索引。",
        severity="error",
    ),
    "weknora_init_failed": ErrorInfo(
        user_message="知识底座初始化未完成，配置修复后可重试索引。",
        operator_message="知识库初始化配置不完整或所选模型不可用。",
        remediation_hint="检查 KB 初始化配置中的 embedding / chat / rerank / multimodal / provider 是否正确。",
        severity="error",
    ),
    "weknora_model_not_found": ErrorInfo(
        user_message="知识底座初始化未完成，配置修复后可重试索引。",
        operator_message="所选底座模型不存在或已被删除。",
        remediation_hint="在模型配置中心确认模型仍存在并重新选择后保存。",
        severity="error",
    ),
    "weknora_default_model_not_configured": ErrorInfo(
        user_message="平台尚未配置默认模型，资产已保存，请联系管理员配置后重试索引。",
        operator_message="平台默认 embedding 模型未配置（weknora_default_models）。",
        remediation_hint="在模型配置中心设置平台默认 embedding 模型后重试索引。",
        severity="error",
    ),
    "weknora_kb_embedding_model_locked": ErrorInfo(
        user_message="该知识库已绑定嵌入模型，如需切换请先重建索引。",
        operator_message="请求选择的 embedding 模型与该 KB 已绑定模型不一致。",
        remediation_hint="沿用 KB 现有 embedding 模型，或走重建索引流程后再切换。",
        severity="warning",
    ),
    "weknora_call_failed": ErrorInfo(
        user_message="知识底座暂时不可用，资产已保存，可稍后重试。",
        operator_message="调用知识底座失败（建库 / 初始化 / 上传 / 检索）。",
        remediation_hint="检查 WeKnora 服务可达性、认证与响应状态，以及后端网络。",
        severity="error",
    ),
    "source_file_unreadable": ErrorInfo(
        user_message="原文来源暂不可用，需要重新上传或联系管理员。",
        operator_message="平台存储中的源文件不可读。",
        remediation_hint="检查平台存储路径、后端 / worker 共享卷，以及源文件是否仍存在。",
        severity="error",
    ),
    "wecom_scan_failed": ErrorInfo(
        user_message="企业微信同步失败，可稍后重试或联系管理员。",
        operator_message="企业微信微盘扫描失败。",
        remediation_hint="检查 WeCom 凭证、目录配置、业务归属人是否仍有效，以及扫描任务记录。",
        severity="error",
    ),
    "unknown": ErrorInfo(
        user_message="知识底座处理失败，可稍后重试或联系管理员。",
        operator_message="未分类的底座处理失败。",
        remediation_hint="查看 trace 与后端日志定位；勿在响应中回显上游原文。",
        severity="error",
    ),
}

# 原始安全 code → 目录分类键（messaging 用；不改各模块持久化的原始 error_code）。
_ALIASES: dict[str, str] = {
    "weknora_down": "weknora_call_failed",
    "weknora_unreachable": "weknora_call_failed",
    "weknora_index_failed": "weknora_call_failed",
    "weknora_upload_failed": "weknora_call_failed",
    "http_error": "weknora_call_failed",
    "invalid_response": "weknora_call_failed",
    "create_kb_no_id": "weknora_init_failed",
}


def _resolve_key(code: str | None) -> str:
    raw = (code or "").strip() or "unknown"
    if raw in _CATALOG:
        return raw
    if raw in _ALIASES:
        return _ALIASES[raw]
    if raw.startswith("http_") or raw.startswith("weknora"):
        return "weknora_call_failed"
    if raw.startswith("wecom"):
        return "wecom_scan_failed"
    return "unknown"


def get_error(code: str | None) -> ErrorInfo:
    """按安全 error_code 取目录条目（allowlist；未知 → unknown 安全文案）。"""
    return _CATALOG[_resolve_key(code)]


def user_message(code: str | None) -> str:
    """业务用户态安全文案。"""
    return get_error(code).user_message


def safe_code(code: str | None) -> str:
    """归一化为**安全目录 code**（allowlist/alias，非正则放行）——供 DB 写入 / 响应 / 审计。

    上游 `WeKnoraError.code` 也是外部输入、不可信（可能含 sk-/url/真实 model·kb id），因此
    一律映射为目录分类 code：已知→自身、别名→目录 code、未知/不可信→`unknown`。幂等。
    """
    return _resolve_key(code)

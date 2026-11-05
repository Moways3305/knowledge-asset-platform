"""Server-owned protocol templates. Model names remain user supplied, never treated as entitlement."""

import re
from typing import TypedDict
from urllib.parse import urlsplit

from app.schemas.model_registry import Capability, ConnectionInput


class RegistryError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        self.code, self.message, self.status = code, message, status
        super().__init__(code)


class ProviderFields(TypedDict):
    id: str
    name: str
    base: str
    capabilities: list[Capability]


class ProviderTemplate(ProviderFields, total=False):
    workspace: bool


# Only capabilities supported by both the adapter and the current runtime are advertised.
CATALOG: list[ProviderTemplate] = [
    {
        "id": "aliyun",
        "name": "阿里云百炼",
        "base": "",
        "capabilities": ["chat", "embedding", "rerank"],
        "workspace": True,
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "base": "https://api.deepseek.com/v1",
        "capabilities": ["chat"],
    },
    {
        "id": "siliconflow",
        "name": "硅基流动",
        "base": "https://api.siliconflow.cn/v1",
        "capabilities": ["chat", "embedding", "rerank"],
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "base": "https://api.openai.com/v1",
        "capabilities": ["chat", "embedding"],
    },
    {
        "id": "moonshot",
        "name": "Moonshot / Kimi",
        "base": "https://api.moonshot.cn/v1",
        "capabilities": ["chat"],
    },
    {
        "id": "zhipu",
        "name": "智谱",
        "base": "https://open.bigmodel.cn/api/paas/v4",
        "capabilities": ["chat", "embedding"],
    },
    {
        "id": "volcengine",
        "name": "火山方舟",
        "base": "https://ark.cn-beijing.volces.com/api/v3",
        "capabilities": ["chat"],
    },
    {
        "id": "custom",
        "name": "自定义兼容服务",
        "base": "",
        "capabilities": ["chat", "embedding", "rerank"],
    },
]


def validate_url(value: str) -> str:
    url = value.strip().rstrip("/")
    try:
        parsed = urlsplit(url)
        port = parsed.port
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or port == 0
            or any(c.isspace() for c in url)
        ):
            raise ValueError()
    except ValueError:
        raise RegistryError(
            "invalid_endpoint",
            "接口地址必须是完整 HTTP(S) 地址，不能包含用户信息、查询参数或片段。",
        ) from None
    return url


def endpoints_for(body: ConnectionInput) -> dict:
    result: dict[str, dict[str, str]]
    provider = next((p for p in CATALOG if p["id"] == body.provider), None)
    if not provider:
        raise RegistryError("unsupported_provider", "请选择支持的供应商或自定义兼容服务。")
    if body.endpoints is not None:
        if not body.endpoints:
            raise RegistryError("endpoint_required", "请至少配置一个能力接口。")
        result = {
            cap: {"url": validate_url(ep.url.get_secret_value()), "protocol": ep.protocol}
            for cap, ep in body.endpoints.items()
        }
    elif body.provider == "aliyun":
        if body.region not in {"cn-beijing", "cn-hongkong", "ap-southeast-1"}:
            raise RegistryError(
                "unsupported_region", "请选择支持的地域，其他地域可使用自定义接口。"
            )
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]{1,98}", body.workspace_id):
            raise RegistryError("workspace_required", "请填写业务空间 ID，或在高级配置中指定接口。")
        host = f"https://{body.workspace_id}.{body.region}.maas.aliyuncs.com"
        result = {
            cap: {"url": host + "/compatible-mode/v1", "protocol": "openai"}
            for cap in ("chat", "embedding")
        }
        result["rerank"] = {
            "url": host + "/api/v1/services/rerank/text-rerank/text-rerank",
            "protocol": "dashscope",
        }
    elif provider["base"]:
        result = {
            cap: {
                "url": provider["base"] + ("/rerank" if cap == "rerank" else ""),
                "protocol": "rerank" if cap == "rerank" else "openai",
            }
            for cap in provider["capabilities"]
        }
    else:
        raise RegistryError("endpoint_required", "自定义服务需要填写能力接口。")
    for cap, ep in result.items():
        if (
            cap not in provider["capabilities"]
            or (cap != "rerank" and ep["protocol"] != "openai")
            or (cap == "rerank" and ep["protocol"] not in {"rerank", "dashscope"})
        ):
            raise RegistryError("protocol_mismatch", "所选供应商、模型能力与接口协议不匹配。")
        if cap != "rerank" and ep["url"].endswith(("/chat/completions", "/embeddings")):
            raise RegistryError(
                "base_url_required",
                "对话和嵌入请填写 Base URL，不要包含 /chat/completions 或 /embeddings。",
            )
    return result

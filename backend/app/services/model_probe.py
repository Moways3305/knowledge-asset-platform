"""Small synthetic probes through explicit protocol adapters. No provider body is persisted."""

import asyncio
import ipaddress
import math
import socket
from urllib.parse import urlsplit

import httpx

from app.core.config import get_settings
from app.services.model_provider_catalog import RegistryError, validate_url

MESSAGES = {
    "verified": "当前配置验证通过。",
    "untested": "当前配置尚未验证。",
    "credentials": "凭据无效或已失效，请检查并更新凭据。",
    "workspace_denied": "业务空间拒绝访问，请检查凭据所属空间及授权。",
    "account_arrears": "服务商返回账户欠费，请检查账户状态。",
    "quota_exhausted": "服务商返回配额不足，请检查可用额度。",
    "access_denied": "服务商拒绝访问，请检查模型授权。",
    "endpoint_or_model": "接口或模型不存在，请核对协议、接口和模型名称。",
    "rate_limited": "调用受到限流，请稍后重试。",
    "timeout": "服务请求超时，可稍后重试。",
    "network": "无法连接模型服务，请检查网络和接口。",
    "https_required": "公网模型接口必须使用 HTTPS。",
    "endpoint_blocked": "该接口不在允许访问的网络范围，请检查已批准的模型网关配置。",
    "invalid_response": "返回内容不符合所选能力协议。",
    "dimension_mismatch": "实际向量维度与配置不一致。",
    "provider_error": "模型服务返回错误，请核对配置后重试。",
    "sync_failed": "模型已验证，但用途接入尚未完成；可重试接入。",
    "creation_unconfirmed": "上次创建结果尚未确认；重试会先查找已有记录，不会重复创建。",
    "credential_unconfirmed": "用途端凭据写入未确认，可重试接入。",
    "stale": "配置已变化，请重新验证。",
    "runtime_check_failed": "供应商验证通过，但用途端验证失败，请检查底座连接后重试。",
}


def message(code):
    return MESSAGES.get(code, "操作未完成，请检查配置后重试。")


def error_code(status, data):
    # Exact known provider codes only. Never infer account standing from a generic 400/403.
    nested = data.get("error", {}) if isinstance(data, dict) else {}
    code = data.get("code") if isinstance(data, dict) else None
    if isinstance(nested, dict):
        code = nested.get("code") or nested.get("type") or code
    codes = {
        "Arrearage": "account_arrears",
        "Endpoint.AccessDenied": "workspace_denied",
        "insufficient_quota": "quota_exhausted",
        "InvalidApiKey": "credentials",
    }
    return codes.get(
        str(code),
        {
            401: "credentials",
            403: "access_denied",
            404: "endpoint_or_model",
            429: "rate_limited",
        }.get(status, "provider_error"),
    )


async def post_probe(url: str, key: str, payload: dict) -> dict:
    url = validate_url(url)
    parts = urlsplit(url)
    host = parts.hostname
    allowed = {
        h.strip().lower()
        for h in get_settings().model_registry_private_hosts.split(",")
        if h.strip()
    }
    if parts.scheme != "https" and host not in allowed:
        raise RegistryError("https_required", "公网模型接口必须使用 HTTPS。")
    try:
        infos = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(
                host,
                parts.port or (443 if parts.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            ),
            timeout=5,
        )
        addresses = sorted({item[4][0] for item in infos})
        if not addresses or (
            host not in allowed and any(not ipaddress.ip_address(ip).is_global for ip in addresses)
        ):
            raise RegistryError("endpoint_blocked", "该接口地址不在允许访问的网络范围。")
        # Pin the validated address for the request, while preserving TLS SNI and Host.
        target = httpx.URL(url).copy_with(host=addresses[0])
        headers = {
            "Host": parts.netloc,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=20, trust_env=False, follow_redirects=False) as client:
            async with client.stream(
                "POST", target, headers=headers, json=payload, extensions={"sni_hostname": host}
            ) as response:
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > 2_000_000:
                        raise RegistryError("invalid_response", message("invalid_response"))
                import json

                try:
                    body = json.loads(data)
                except (ValueError, UnicodeError):
                    body = {}
                if not 200 <= response.status_code < 300:
                    code = error_code(response.status_code, body)
                    raise RegistryError(code, message(code))
                return body
    except (httpx.TimeoutException, asyncio.TimeoutError):
        raise RegistryError("timeout", message("timeout")) from None
    except (httpx.HTTPError, OSError):
        raise RegistryError("network", message("network")) from None


async def probe(endpoint, key, name, capability, dimension=None, provider="custom"):
    url, protocol = endpoint["url"], endpoint["protocol"]
    payload = {"model": name}
    if capability == "chat":
        url += "/chat/completions"
        payload.update(
            messages=[{"role": "user", "content": "Reply OK."}], stream=False, max_tokens=128
        )
        if provider == "deepseek":
            payload["thinking"] = {"type": "disabled"}
    elif capability == "embedding":
        url += "/embeddings"
        payload["input"] = ["Synthetic model connection check."]
        if dimension:
            payload["dimensions"] = dimension
    elif protocol == "dashscope":
        payload.update(
            input={"query": "blue", "documents": ["blue sky", "red apple"]},
            parameters={"top_n": 2, "return_documents": False},
        )
    else:
        payload.update(query="blue", documents=["blue sky", "red apple"], top_n=2)
    body = await post_probe(url, key, payload)
    try:
        if capability == "chat":
            content = body["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError()
        elif capability == "embedding":
            values = body["data"]
            if len(values) != 1 or values[0].get("index", 0) != 0:
                raise ValueError()
            vector = values[0]["embedding"]
            if (
                not isinstance(vector, list)
                or not vector
                or len(vector) > 65536
                or not all(type(x) in (int, float) and math.isfinite(x) for x in vector)
            ):
                raise ValueError()
            if dimension and len(vector) != dimension:
                raise RegistryError("dimension_mismatch", message("dimension_mismatch"))
            return len(vector)
        else:
            results = (body["output"] if protocol == "dashscope" else body)["results"]
            if not isinstance(results, list) or len(results) != 2:
                raise ValueError()
            indices = [r["index"] for r in results]
            if any(type(i) is not int for i in indices) or set(indices) != {0, 1}:
                raise ValueError()
            scores = [r["relevance_score"] for r in results]
            if (
                not all(type(v) in (int, float) and math.isfinite(v) for v in scores)
                or scores[0] < scores[1]
            ):
                raise ValueError()
    except (KeyError, TypeError, ValueError, IndexError, AttributeError):
        raise RegistryError("invalid_response", message("invalid_response")) from None
    return None

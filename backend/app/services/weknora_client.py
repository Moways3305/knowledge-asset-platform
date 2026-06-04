"""WeKnora 底座 HTTP 客户端（R1）。

封装对 WeKnora REST 的唯一访问入口（base `${WEKNORA_BASE_URL}/api/v1`，header
`X-API-Key` + `X-Request-ID=trace_id`）。业务代码**不得**直接发 HTTP 到 WeKnora。

安全红线：
- `X-API-Key`（`sk-` 前缀）、`weknora_kb_id` / `knowledge_id` / `file_path` 等
  **绝不**写日志 / 审计 / 响应。本模块异常 `WeKnoraError` 只带 code/message，不带 key。
- 响应统一包 `{success, data, error{code,message,details}}`；非 success 抛 `WeKnoraError`。
  HTTP 409（文件重复）抛 `WeKnoraDuplicateError`（带已存在 knowledge id，供去重复用）。

dev/降级：`WEKNORA_BASE_URL` 或 `WEKNORA_API_KEY` 未配置 → `weknora_enabled()` 为 False，
依赖返回 `NullWeKnoraClient`（任何调用抛 `weknora_not_configured`），confirm 据此跳过
索引，app 仍可起。测试经依赖覆盖注入 fake client，不打真实网络。
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.config import get_settings


class WeKnoraError(Exception):
    """WeKnora 调用失败（结构化，不含 api_key）。"""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class WeKnoraDuplicateError(WeKnoraError):
    """上传命中 WeKnora 自带 file_hash 去重（HTTP 409）。携带已存在 knowledge id。"""

    def __init__(self, existing_knowledge_id: str | None) -> None:
        self.existing_knowledge_id = existing_knowledge_id
        super().__init__("knowledge_duplicate", "文件内容已存在于该知识库")


class WeKnoraClient:
    """真实 WeKnora 客户端（httpx 异步）。"""

    def __init__(self, *, base_url: str, api_key: str, timeout: float = 30.0) -> None:
        if not api_key.startswith("sk-"):
            # 不把 key 值放进异常信息。
            raise WeKnoraError("invalid_api_key", "WeKnora API Key 格式非法（应以 sk- 开头）")
        self._base = base_url.rstrip("/") + "/api/v1"
        self._api_key = api_key
        self._timeout = timeout

    def _headers(self, trace_id: str | None) -> dict[str, str]:
        h = {"X-API-Key": self._api_key}
        if trace_id:
            h["X-Request-ID"] = trace_id
        return h

    @staticmethod
    def _unwrap(resp: httpx.Response) -> dict[str, Any]:
        """解析统一响应包；非 success / 错误状态抛结构化错误（不含 api_key）。"""
        if resp.status_code == 409:
            existing = None
            try:
                data = resp.json().get("data") or {}
                existing = data.get("id") or data.get("knowledge_id")
            except Exception:  # noqa: BLE001
                existing = None
            raise WeKnoraDuplicateError(existing)
        try:
            body = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise WeKnoraError("invalid_response", f"WeKnora 响应非 JSON（HTTP {resp.status_code}）") from exc
        if resp.status_code >= 400 or not body.get("success", resp.status_code < 400):
            err = body.get("error") or {}
            raise WeKnoraError(
                str(err.get("code") or f"http_{resp.status_code}"),
                str(err.get("message") or "WeKnora 调用失败"),
            )
        return body.get("data") or {}

    async def create_kb(
        self, *, name: str, embedding_model_id: str | None, trace_id: str | None = None,
        description: str = "", summary_model_id: str | None = None,
    ) -> str:
        """建知识库，返回 weknora_kb_id。embedding_model_id 全平台统一、建库后不可改。"""
        payload: dict[str, Any] = {"name": name, "description": description, "type": "document"}
        if embedding_model_id:
            payload["embedding_model_id"] = embedding_model_id
        if summary_model_id:
            payload["summary_model_id"] = summary_model_id
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base}/knowledge-bases", json=payload, headers=self._headers(trace_id)
            )
        data = self._unwrap(resp)
        kb_id = data.get("id")
        if not kb_id:
            raise WeKnoraError("create_kb_no_id", "WeKnora 建库未返回 id")
        return str(kb_id)

    async def get_kb(self, kb_id: str, *, trace_id: str | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base}/knowledge-bases/{kb_id}", headers=self._headers(trace_id)
            )
        return self._unwrap(resp)

    async def upload_file(
        self, *, kb_id: str, content: bytes, file_name: str, mime: str | None,
        metadata: dict[str, Any] | None = None, channel: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """上传文件创建知识，返回 data（含 id=knowledge id、parse_status、file_hash）。"""
        files = {"file": (file_name, content, mime or "application/octet-stream")}
        form: dict[str, str] = {}
        if metadata:
            form["metadata"] = json.dumps(metadata, ensure_ascii=False)
        if channel:
            form["channel"] = channel
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base}/knowledge-bases/{kb_id}/knowledge/file",
                files=files, data=form, headers=self._headers(trace_id),
            )
        return self._unwrap(resp)

    async def get_knowledge(self, knowledge_id: str, *, trace_id: str | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base}/knowledge/{knowledge_id}", headers=self._headers(trace_id)
            )
        return self._unwrap(resp)

    @staticmethod
    def _normalize_chunks(data: Any) -> list[dict[str, Any]]:
        """把 WeKnora 检索响应 data 规整为统一 chunk 列表。

        兼容 data 直接是列表、或包成 `{results|chunks|list: [...]}`。每个 chunk 只取
        检索/映射/脱敏所需的安全字段：content / knowledge_id / chunk_index / score /
        seq / start / end。**绝不**把整段 WeKnora 原始结构原样外泄给上层。
        """
        if isinstance(data, dict):
            items = data.get("results") or data.get("chunks") or data.get("list") or []
        elif isinstance(data, list):
            items = data
        else:
            items = []
        out: list[dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            knowledge_id = it.get("knowledge_id") or it.get("doc_id")
            nested = it.get("knowledge")
            if not knowledge_id and isinstance(nested, dict):
                knowledge_id = nested.get("id")
            if not knowledge_id:
                continue
            out.append(
                {
                    "content": str(it.get("content") or it.get("text") or ""),
                    "knowledge_id": str(knowledge_id),
                    "chunk_index": it.get("chunk_index"),
                    "score": float(it.get("score") or it.get("relevance_score") or 0.0),
                    "seq": it.get("seq") if it.get("seq") is not None else it.get("chunk_index"),
                    "start": it.get("start") if it.get("start") is not None else it.get("start_offset"),
                    "end": it.get("end") if it.get("end") is not None else it.get("end_offset"),
                }
            )
        return out

    async def search(
        self,
        *,
        query: str,
        kb_ids: list[str],
        knowledge_ids: list[str] | None = None,
        top_k: int = 20,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """核心检索：`POST /knowledge-search`。

        kb_ids 限定可检索的知识库（scope 路由预过滤）；knowledge_ids 进一步限定到
        指定知识（阶段2取某资产原文 chunk 时用）。返回规整后的 chunk 列表。
        """
        payload: dict[str, Any] = {"query": query, "knowledge_base_ids": kb_ids, "top_k": top_k}
        if knowledge_ids:
            payload["knowledge_ids"] = knowledge_ids
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base}/knowledge-search", json=payload, headers=self._headers(trace_id)
            )
        return self._normalize_chunks(self._unwrap(resp))

    async def hybrid_search(
        self,
        *,
        kb_id: str,
        query: str,
        top_k: int = 20,
        vector_threshold: float | None = None,
        keyword_threshold: float | None = None,
        trace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """带阈值的混合召回：`GET /knowledge-bases/:kb/hybrid-search`（JSON body）。"""
        body: dict[str, Any] = {"query": query, "top_k": top_k}
        if vector_threshold is not None:
            body["vector_threshold"] = vector_threshold
        if keyword_threshold is not None:
            body["keyword_threshold"] = keyword_threshold
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            # WeKnora hybrid-search 用 GET + JSON body（照 swagger）。
            resp = await client.request(
                "GET",
                f"{self._base}/knowledge-bases/{kb_id}/hybrid-search",
                json=body,
                headers=self._headers(trace_id),
            )
        return self._normalize_chunks(self._unwrap(resp))

    async def delete_knowledge(self, knowledge_id: str, *, trace_id: str | None = None) -> None:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.delete(
                f"{self._base}/knowledge/{knowledge_id}", headers=self._headers(trace_id)
            )
        self._unwrap(resp)


class NullWeKnoraClient:
    """未配置 WeKnora 时的占位客户端：任何调用抛 not_configured（confirm 据此跳过索引）。"""

    async def create_kb(self, **_: Any) -> str:
        raise WeKnoraError("weknora_not_configured", "WeKnora 未配置")

    async def get_kb(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise WeKnoraError("weknora_not_configured", "WeKnora 未配置")

    async def upload_file(self, **_: Any) -> dict[str, Any]:
        raise WeKnoraError("weknora_not_configured", "WeKnora 未配置")

    async def get_knowledge(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise WeKnoraError("weknora_not_configured", "WeKnora 未配置")

    async def delete_knowledge(self, *_: Any, **__: Any) -> None:
        raise WeKnoraError("weknora_not_configured", "WeKnora 未配置")

    async def search(self, **_: Any) -> list[dict[str, Any]]:
        # 未配置底座：返回空召回（检索降级为"无结果"，不抛错阻断请求）。
        return []

    async def hybrid_search(self, **_: Any) -> list[dict[str, Any]]:
        return []


def weknora_enabled() -> bool:
    """base_url + api_key 同时配置才启用真实集成。"""
    s = get_settings()
    return bool(s.weknora_base_url and s.weknora_api_key)


def get_weknora_client() -> WeKnoraClient | NullWeKnoraClient:
    """FastAPI 依赖：配置齐全 → 真实客户端；否则 → NullWeKnoraClient。

    测试经 `app.dependency_overrides[get_weknora_client]` 注入 fake，不打真实网络。
    """
    if not weknora_enabled():
        return NullWeKnoraClient()
    s = get_settings()
    return WeKnoraClient(
        base_url=s.weknora_base_url, api_key=s.weknora_api_key, timeout=s.weknora_timeout
    )

"""WeKnora 底座 HTTP 客户端。

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
import logging
import time
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import safe_log_exception

_logger = logging.getLogger(__name__)


def _resource_of(path: str) -> str:
    """仅取 URL 的**首层资源名**（REST 中首段恒为资源、绝不是 id），其余段（可能含
    weknora_kb_id / knowledge_id 等 server-only 标识）一律不入日志。例如
    `/knowledge-bases/wk-kb-x/files` → `/knowledge-bases`、`/models/uuid` → `/models`。"""
    segs = [s for s in path.split("/") if s]
    return "/" + segs[0] if segs else "/"


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
            except Exception as exc:  # noqa: BLE001
                safe_log_exception(_logger, "weknora_409_parse_failed", exc, level=logging.WARNING)
                existing = None
            raise WeKnoraDuplicateError(existing)
        try:
            body = resp.json()
        except Exception as exc:  # noqa: BLE001
            safe_log_exception(_logger, "weknora_response_not_json", exc, status=resp.status_code)
            raise WeKnoraError(
                "invalid_response", f"WeKnora 响应非 JSON（HTTP {resp.status_code}）"
            ) from exc
        if resp.status_code >= 400 or not body.get("success", resp.status_code < 400):
            err = body.get("error") or {}
            raise WeKnoraError(
                str(err.get("code") or f"http_{resp.status_code}"),
                str(err.get("message") or "WeKnora 调用失败"),
            )
        return body.get("data") or {}

    async def create_kb(
        self,
        *,
        name: str,
        embedding_model_id: str | None,
        trace_id: str | None = None,
        description: str = "",
        summary_model_id: str | None = None,
    ) -> str:
        """建知识库，返回 weknora_kb_id。embedding_model_id 全平台统一、建库后不可改。"""
        payload: dict[str, Any] = {"name": name, "description": description, "type": "document"}
        if embedding_model_id:
            payload["embedding_model_id"] = embedding_model_id
        if summary_model_id:
            payload["summary_model_id"] = summary_model_id
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base}/knowledge-bases", json=payload, headers=self._headers(trace_id)
            )
        _logger.info(
            "weknora_call",
            extra={
                "method": "POST",
                "resource": "/knowledge-bases",
                "status": resp.status_code,
                "latency_ms": round((time.perf_counter() - start) * 1000, 1),
            },
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

    async def update_kb(
        self,
        kb_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """改 KB 名称 / 描述（`PUT /knowledge-bases/:id`）。

        只发送 name / description；**不**开放 chunking_config / storage_config 等底层配置
        （风险高，由专门的底座配置入口管理）。错误经 `_unwrap` 抛结构化 `WeKnoraError`，不含 api_key。
        """
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if description is not None:
            payload["description"] = description
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.put(
                f"{self._base}/knowledge-bases/{kb_id}",
                json=payload,
                headers=self._headers(trace_id),
            )
        return self._unwrap(resp)

    async def get_initialization_config(
        self, kb_id: str, *, trace_id: str | None = None
    ) -> dict[str, Any]:
        """读 KB 当前模型初始化配置（`GET /initialization/config/:kb_id`）。

        返回 chat/embedding/rerank/multimodal 模型 id（WeKnora 内部 id，server-only，
        绝不外泄前端 / 审计）。供运维诊断「KB 是否已配齐模型」。
        """
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base}/initialization/config/{kb_id}", headers=self._headers(trace_id)
            )
        return self._unwrap(resp)

    async def initialize_kb(
        self,
        kb_id: str,
        *,
        chat_model_id: str | None = None,
        embedding_model_id: str | None = None,
        rerank_model_id: str | None = None,
        multimodal_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        """初始化 KB 的模型配置（`POST /initialization/initialize/:kb_id`）。

        只发送非空模型 id（部分配置也写入，确保至少有 embedding）。失败抛 `WeKnoraError`
        （结构化 code/message，不含 api_key / 模型内部 id 调试 payload），由调用方据此进入
        可诊断的 index_failed / init_failed 状态——**绝不**静默假成功。
        """
        payload: dict[str, Any] = {}
        if chat_model_id:
            payload["chat_model_id"] = chat_model_id
        if embedding_model_id:
            payload["embedding_model_id"] = embedding_model_id
        if rerank_model_id:
            payload["rerank_model_id"] = rerank_model_id
        if multimodal_id:
            payload["multimodal_id"] = multimodal_id
        if not payload:
            # 无任何模型 id 可写：跳过初始化（KB 依赖 WeKnora 租户默认）。不报错，但也不假装已配。
            return
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base}/initialization/initialize/{kb_id}",
                json=payload,
                headers=self._headers(trace_id),
            )
        self._unwrap(resp)

    async def upload_file(
        self,
        *,
        kb_id: str,
        content: bytes,
        file_name: str,
        mime: str | None,
        metadata: dict[str, Any] | None = None,
        channel: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """上传文件创建知识，返回 data（含 id=knowledge id、parse_status、file_hash）。"""
        files = {"file": (file_name, content, mime or "application/octet-stream")}
        form: dict[str, str] = {}
        if metadata:
            form["metadata"] = json.dumps(metadata, ensure_ascii=False)
        if channel:
            form["channel"] = channel
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base}/knowledge-bases/{kb_id}/knowledge/file",
                files=files,
                data=form,
                headers=self._headers(trace_id),
            )
        _logger.info(
            "weknora_call",
            extra={
                "method": "POST",
                "resource": "/knowledge-bases/{kb_id}/knowledge/file",  # 静态模板，无真实 id
                "status": resp.status_code,
                "latency_ms": round((time.perf_counter() - start) * 1000, 1),
            },
        )
        return self._unwrap(resp)

    async def get_knowledge(
        self, knowledge_id: str, *, trace_id: str | None = None
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base}/knowledge/{knowledge_id}", headers=self._headers(trace_id)
            )
        return self._unwrap(resp)

    async def reparse_knowledge(
        self,
        *,
        kb_id: str,
        knowledge_id: str | None,
        content: bytes,
        file_name: str,
        mime: str | None,
        metadata: dict[str, Any] | None = None,
        channel: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """显式 reparse：WeKnora **无独立 reparse 端点**，本方法封装为「受控重传」——
        先删除已有 doc（若有），再重新上传同一原文触发底座重新解析，返回**新 doc** data
        （含 id=新 knowledge id、parse_status、file_hash）。

        与 retry-index 的差异：retry-index 用于尚未进底座的资产（建库 + 首次上传）；reparse
        用于**已进底座但解析状态异常**的资产，强制刷新解析（会更新 weknora_doc_id 为新 doc）。
        删除失败（doc 可能已不存在）不阻断重传。异常经 `_unwrap` 不带 api_key / 内部 id。
        """
        if knowledge_id:
            try:
                await self.delete_knowledge(knowledge_id, trace_id=trace_id)
            except WeKnoraError:
                # doc 可能已不存在 / 底座删除失败：不阻断重传，继续上传新 doc。
                pass
        return await self.upload_file(
            kb_id=kb_id,
            content=content,
            file_name=file_name,
            mime=mime,
            metadata=metadata,
            channel=channel,
            trace_id=trace_id,
        )

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
                    "start": it.get("start")
                    if it.get("start") is not None
                    else it.get("start_offset"),
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

    # ---- 模型与初始化配置管理（管理面）----
    # 这些方法返回 WeKnora 原始 dict（含 server-only id / 已脱敏 key），**上层 service 负责
    # 再脱敏 / 映射 model_ref 后才出 API**——本层只保证错误经 `_unwrap` 不带 api_key。
    async def _call(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> Any:
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.request(
                method, f"{self._base}{path}", json=json, headers=self._headers(trace_id)
            )
        _logger.info(
            "weknora_call",
            extra={
                "method": method,
                "resource": _resource_of(path),  # 仅资源名，绝不含 kb/doc id
                "status": resp.status_code,
                "latency_ms": round((time.perf_counter() - start) * 1000, 1),
            },
        )
        return self._unwrap(resp)

    async def list_model_providers(
        self, model_type: str | None = None, *, trace_id: str | None = None
    ) -> list[dict[str, Any]]:
        path = "/models/providers"
        if model_type:
            path += f"?model_type={model_type}"
        data = await self._call("GET", path, trace_id=trace_id)
        return (
            data
            if isinstance(data, list)
            else (data.get("items") if isinstance(data, dict) else []) or []
        )

    async def list_models(self, *, trace_id: str | None = None) -> list[dict[str, Any]]:
        data = await self._call("GET", "/models", trace_id=trace_id)
        return (
            data
            if isinstance(data, list)
            else (data.get("items") if isinstance(data, dict) else []) or []
        )

    async def get_model(self, model_id: str, *, trace_id: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = await self._call("GET", f"/models/{model_id}", trace_id=trace_id)
        return result

    async def create_model(
        self, payload: dict[str, Any], *, trace_id: str | None = None
    ) -> dict[str, Any]:
        result: dict[str, Any] = await self._call(
            "POST", "/models", json=payload, trace_id=trace_id
        )
        return result

    async def update_model(
        self, model_id: str, payload: dict[str, Any], *, trace_id: str | None = None
    ) -> dict[str, Any]:
        result: dict[str, Any] = await self._call(
            "PUT", f"/models/{model_id}", json=payload, trace_id=trace_id
        )
        return result

    async def delete_model(self, model_id: str, *, trace_id: str | None = None) -> None:
        await self._call("DELETE", f"/models/{model_id}", trace_id=trace_id)

    async def update_initialization_config(
        self,
        kb_id: str,
        *,
        chat_model_id: str | None = None,
        embedding_model_id: str | None = None,
        rerank_model_id: str | None = None,
        multimodal_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any] | None:
        """更新 KB 模型初始化配置（`PUT /initialization/config/:kb_id`）。只发非空字段。"""
        payload: dict[str, Any] = {}
        if chat_model_id:
            payload["chat_model_id"] = chat_model_id
        if embedding_model_id:
            payload["embedding_model_id"] = embedding_model_id
        if rerank_model_id:
            payload["rerank_model_id"] = rerank_model_id
        if multimodal_id:
            payload["multimodal_id"] = multimodal_id
        if not payload:
            return None
        result: dict[str, Any] = await self._call(
            "PUT", f"/initialization/config/{kb_id}", json=payload, trace_id=trace_id
        )
        return result

    async def _model_check(
        self, path: str, *, api_url: str, api_key: str, model: str, trace_id: str | None
    ) -> dict[str, Any]:
        body = {"api_url": api_url, "api_key": api_key, "model": model}
        result: dict[str, Any] = await self._call("POST", path, json=body, trace_id=trace_id)
        return result

    async def check_remote_model(
        self, *, api_url: str, api_key: str, model: str, trace_id: str | None = None
    ) -> dict[str, Any]:
        return await self._model_check(
            "/initialization/remote/check",
            api_url=api_url,
            api_key=api_key,
            model=model,
            trace_id=trace_id,
        )

    async def test_embedding_model(
        self, *, api_url: str, api_key: str, model: str, trace_id: str | None = None
    ) -> dict[str, Any]:
        return await self._model_check(
            "/initialization/embedding/test",
            api_url=api_url,
            api_key=api_key,
            model=model,
            trace_id=trace_id,
        )

    async def check_rerank_model(
        self, *, api_url: str, api_key: str, model: str, trace_id: str | None = None
    ) -> dict[str, Any]:
        return await self._model_check(
            "/initialization/rerank/check",
            api_url=api_url,
            api_key=api_key,
            model=model,
            trace_id=trace_id,
        )

    async def test_multimodal_model(
        self, *, api_url: str, api_key: str, model: str, trace_id: str | None = None
    ) -> dict[str, Any]:
        return await self._model_check(
            "/initialization/multimodal/test",
            api_url=api_url,
            api_key=api_key,
            model=model,
            trace_id=trace_id,
        )


class NullWeKnoraClient:
    """未配置 WeKnora 时的占位客户端：任何调用抛 not_configured（confirm 据此跳过索引）。"""

    async def create_kb(self, **_: Any) -> str:
        raise WeKnoraError("weknora_not_configured", "WeKnora 未配置")

    async def get_kb(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise WeKnoraError("weknora_not_configured", "WeKnora 未配置")

    async def update_kb(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise WeKnoraError("weknora_not_configured", "WeKnora 未配置")

    async def get_initialization_config(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise WeKnoraError("weknora_not_configured", "WeKnora 未配置")

    async def initialize_kb(self, *_: Any, **__: Any) -> None:
        raise WeKnoraError("weknora_not_configured", "WeKnora 未配置")

    async def upload_file(self, **_: Any) -> dict[str, Any]:
        raise WeKnoraError("weknora_not_configured", "WeKnora 未配置")

    async def get_knowledge(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise WeKnoraError("weknora_not_configured", "WeKnora 未配置")

    async def reparse_knowledge(self, **_: Any) -> dict[str, Any]:
        raise WeKnoraError("weknora_not_configured", "WeKnora 未配置")

    async def delete_knowledge(self, *_: Any, **__: Any) -> None:
        raise WeKnoraError("weknora_not_configured", "WeKnora 未配置")

    async def search(self, **_: Any) -> list[dict[str, Any]]:
        # 未配置底座：返回空召回（检索降级为"无结果"，不抛错阻断请求）。
        return []

    async def hybrid_search(self, **_: Any) -> list[dict[str, Any]]:
        return []

    # 管理面：未配置时一律 not_configured（API 层转安全 503 / missing config）。
    async def list_model_providers(self, *_: Any, **__: Any) -> list[dict[str, Any]]:
        raise WeKnoraError("weknora_not_configured", "WeKnora 未配置")

    async def list_models(self, *_: Any, **__: Any) -> list[dict[str, Any]]:
        raise WeKnoraError("weknora_not_configured", "WeKnora 未配置")

    async def get_model(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise WeKnoraError("weknora_not_configured", "WeKnora 未配置")

    async def create_model(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise WeKnoraError("weknora_not_configured", "WeKnora 未配置")

    async def update_model(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise WeKnoraError("weknora_not_configured", "WeKnora 未配置")

    async def delete_model(self, *_: Any, **__: Any) -> None:
        raise WeKnoraError("weknora_not_configured", "WeKnora 未配置")

    async def update_initialization_config(self, *_: Any, **__: Any) -> dict[str, Any] | None:
        raise WeKnoraError("weknora_not_configured", "WeKnora 未配置")

    async def check_remote_model(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise WeKnoraError("weknora_not_configured", "WeKnora 未配置")

    async def test_embedding_model(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise WeKnoraError("weknora_not_configured", "WeKnora 未配置")

    async def check_rerank_model(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise WeKnoraError("weknora_not_configured", "WeKnora 未配置")

    async def test_multimodal_model(self, *_: Any, **__: Any) -> dict[str, Any]:
        raise WeKnoraError("weknora_not_configured", "WeKnora 未配置")


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

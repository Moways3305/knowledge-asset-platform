"""WeKnora 模型选择解析（PBC-38）。

优先级：请求显式 model_ref > 平台默认（weknora_default_models）> fail closed。
embedding 必需；rerank/chat/multimodal 可选（缺省可为 None）。
显式 ref 经 HMAC 反查 server-only model_id；反查失败 → weknora_model_not_found。
embedding 既无显式 ref 也无平台默认 → weknora_default_model_not_configured（不再回退 .env）。

安全：返回 ResolvedModels 含 raw model_id，仅供后端建库 / 初始化使用，**绝不**外泄。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import weknora_defaults
from app.services.weknora_client import WeKnoraError
from app.services.weknora_models import _alias, _is_valid_model_name, _model_ref

if TYPE_CHECKING:
    from app.services.weknora_client import NullWeKnoraClient, WeKnoraClient


@dataclass
class ModelInitMeta:
    model_id: str
    source: str
    model_name: str
    type: str


@dataclass
class ResolvedModels:
    embedding_model_id: str
    explicit_embedding: bool
    chat_model_id: str | None = None
    rerank_model_id: str | None = None
    multimodal_id: str | None = None
    embedding: ModelInitMeta | None = None
    chat: ModelInitMeta | None = None
    models_by_id: dict[str, ModelInitMeta] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.embedding is None and self.embedding_model_id:
            self.embedding = ModelInitMeta(
                self.embedding_model_id, "remote", self.embedding_model_id, "embedding"
            )
        if self.chat is None and self.chat_model_id:
            self.chat = ModelInitMeta(self.chat_model_id, "remote", self.chat_model_id, "chat")
        if self.embedding is not None:
            self.models_by_id.setdefault(self.embedding.model_id, self.embedding)
        if self.chat is not None:
            self.models_by_id.setdefault(self.chat.model_id, self.chat)


def _resolve_ref(ref_map: dict[str, str], ref: str) -> str:
    mid = ref_map.get(ref)
    if mid is None:
        raise WeKnoraError("weknora_model_not_found", "所选模型不存在")
    return mid


def _safe_model_meta(raw: dict) -> ModelInitMeta | None:
    model_id = str(raw.get("id") or "").strip()
    source = str(raw.get("source") or "").strip()
    model_name = str(raw.get("name") or "").strip()
    if not (model_id and source and model_name):
        return None
    return ModelInitMeta(
        model_id=model_id,
        source=source,
        model_name=model_name,
        type=_alias(raw.get("type")),
    )


def _require_model(
    models_by_id: dict[str, ModelInitMeta],
    model_id: str,
    *,
    expected_type: str,
) -> ModelInitMeta:
    meta = models_by_id.get(model_id)
    if meta is None:
        raise WeKnoraError("weknora_model_not_found", "所选模型不存在")
    if not _is_valid_model_name(meta.model_name):
        raise WeKnoraError("weknora_model_name_invalid", "所选模型名称不属于允许的模型家族")
    if meta.type != expected_type:
        raise WeKnoraError("weknora_model_type_mismatch", "所选模型类型与用途不匹配")
    return meta


async def resolve_models_for_kb(
    session: AsyncSession,
    client: WeKnoraClient | NullWeKnoraClient,
    *,
    embedding_model_ref: str | None,
    rerank_model_ref: str | None,
    trace_id: str | None,
) -> ResolvedModels:
    defaults = await weknora_defaults.get_defaults(session)

    explicit_embedding = bool(embedding_model_ref)
    default_embedding_id = (defaults.default_embedding_model_id if defaults else None) or ""
    if not embedding_model_ref and not default_embedding_id.strip():
        raise WeKnoraError(
            "weknora_default_model_not_configured",
            "尚未配置平台默认嵌入模型，请联系管理员在模型配置中设置",
        )

    chat_id = (defaults.default_chat_model_id if defaults else None) or ""
    if not chat_id.strip():
        raise WeKnoraError(
            "weknora_default_model_not_configured",
            "尚未配置平台默认问答模型，请联系管理员在模型配置中设置",
        )

    raw_models = await client.list_models(trace_id=trace_id)
    discovered_models_by_id = {
        meta.model_id: meta
        for meta in (_safe_model_meta(m) for m in raw_models if isinstance(m, dict))
        if meta is not None
    }
    ref_map: dict[str, str] = {
        _model_ref(model_id): model_id for model_id in discovered_models_by_id.keys()
    }

    if embedding_model_ref:
        embedding_id = _resolve_ref(ref_map, embedding_model_ref)
    else:
        embedding_id = default_embedding_id
    embedding = _require_model(discovered_models_by_id, embedding_id, expected_type="embedding")
    chat = _require_model(discovered_models_by_id, chat_id, expected_type="chat")

    rerank_id: str | None = None
    if rerank_model_ref:
        rerank_id = _resolve_ref(ref_map, rerank_model_ref)
    else:
        rerank_id = (defaults.default_rerank_model_id if defaults else None) or None
    if rerank_id:
        _require_model(discovered_models_by_id, rerank_id, expected_type="rerank")

    multimodal_id = (defaults.default_multimodal_model_id if defaults else None) or None
    if multimodal_id:
        _require_model(discovered_models_by_id, multimodal_id, expected_type="vllm")

    approved_models_by_id = {
        model_id: meta
        for model_id, meta in discovered_models_by_id.items()
        if _is_valid_model_name(meta.model_name)
    }

    return ResolvedModels(
        embedding_model_id=embedding_id,
        explicit_embedding=explicit_embedding,
        chat_model_id=chat_id,
        rerank_model_id=rerank_id,
        multimodal_id=multimodal_id,
        embedding=embedding,
        chat=chat,
        models_by_id=approved_models_by_id,
    )

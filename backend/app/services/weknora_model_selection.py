"""WeKnora 模型选择解析（PBC-38）。

优先级：请求显式 model_ref > 平台默认（weknora_default_models）> fail closed。
embedding 必需；rerank/chat/multimodal 可选（缺省可为 None）。
显式 ref 经 HMAC 反查 server-only model_id；反查失败 → weknora_model_not_found。
embedding 既无显式 ref 也无平台默认 → weknora_default_model_not_configured（不再回退 .env）。

安全：返回 ResolvedModels 含 raw model_id，仅供后端建库 / 初始化使用，**绝不**外泄。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import weknora_defaults
from app.services.weknora_client import WeKnoraError
from app.services.weknora_models import _ref_to_id_map

if TYPE_CHECKING:
    from app.services.weknora_client import NullWeKnoraClient, WeKnoraClient


@dataclass
class ResolvedModels:
    embedding_model_id: str
    explicit_embedding: bool
    chat_model_id: str | None = None
    rerank_model_id: str | None = None
    multimodal_id: str | None = None


def _resolve_ref(ref_map: dict[str, str], ref: str) -> str:
    mid = ref_map.get(ref)
    if mid is None:
        raise WeKnoraError("weknora_model_not_found", "所选模型不存在")
    return mid


async def resolve_models_for_kb(
    session: AsyncSession,
    client: WeKnoraClient | NullWeKnoraClient,
    *,
    embedding_model_ref: str | None,
    rerank_model_ref: str | None,
    trace_id: str | None,
) -> ResolvedModels:
    defaults = await weknora_defaults.get_defaults(session)
    # 仅当需要解析显式 ref 时才调底座列模型（默认值直接来自 DB，无需 client）。
    ref_map: dict[str, str] = {}
    if embedding_model_ref or rerank_model_ref:
        ref_map = await _ref_to_id_map(client, trace_id)

    explicit_embedding = bool(embedding_model_ref)
    if embedding_model_ref:
        embedding_id = _resolve_ref(ref_map, embedding_model_ref)
    else:
        embedding_id = (defaults.default_embedding_model_id if defaults else None) or ""
        if not embedding_id.strip():
            raise WeKnoraError(
                "weknora_default_model_not_configured",
                "尚未配置平台默认嵌入模型，请联系管理员在模型配置中设置",
            )

    rerank_id: str | None = None
    if rerank_model_ref:
        rerank_id = _resolve_ref(ref_map, rerank_model_ref)
    else:
        rerank_id = (defaults.default_rerank_model_id if defaults else None) or None

    return ResolvedModels(
        embedding_model_id=embedding_id,
        explicit_embedding=explicit_embedding,
        chat_model_id=(defaults.default_chat_model_id if defaults else None) or None,
        rerank_model_id=rerank_id,
        multimodal_id=(defaults.default_multimodal_model_id if defaults else None) or None,
    )

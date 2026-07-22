# backend/tests/test_weknora_model_selection.py
import pytest

from app.services import weknora_defaults
from app.services import weknora_model_selection as sel
from app.services.weknora_client import WeKnoraError

pytestmark = pytest.mark.asyncio


class _FakeClient:
    """list_models returns raw dicts so _ref_to_id_map can build ref->id."""

    def __init__(self, ids):
        self._ids = ids
        self.list_models_calls = 0

    async def list_models(self, *, trace_id=None):
        self.list_models_calls += 1
        rows = []
        for i in self._ids:
            rows.append(
                {
                    "id": i,
                    "name": f"embedding-{i}",
                    "type": "Embedding",
                    "source": "remote",
                }
            )
        rows.append(
            {
                "id": "chat-default",
                "name": "qwen-plus",
                "type": "KnowledgeQA",
                "source": "remote",
            }
        )
        return rows


def _runtime_rows():
    return [
        {
            "id": "emb-default",
            "name": "text-embedding-v3",
            "type": "Embedding",
            "source": "remote",
        },
        {
            "id": "chat-default",
            "name": "qwen-plus",
            "type": "KnowledgeQA",
            "source": "remote",
        },
        {
            "id": "rerank-default",
            "name": "rerank-v3",
            "type": "Rerank",
            "source": "remote",
        },
        {
            "id": "multimodal-default",
            "name": "qwen-vl-max",
            "type": "VLLM",
            "source": "remote",
        },
    ]


class _StaticClient:
    def __init__(self, rows):
        self.rows = rows

    async def list_models(self, *, trace_id=None):
        return self.rows


async def test_explicit_ref_resolves_to_real_id(db_session):
    from app.services.weknora_models import _model_ref

    client = _FakeClient(["emb-real-1"])
    await weknora_defaults.set_defaults(
        db_session,
        embedding_model_id="emb-default",
        rerank_model_id=None,
        chat_model_id="chat-default",
        multimodal_id=None,
        updated_by=None,
    )
    await db_session.commit()
    ref = _model_ref("emb-real-1")
    res = await sel.resolve_models_for_kb(
        db_session, client, embedding_model_ref=ref, rerank_model_ref=None, trace_id=None
    )
    assert res.embedding_model_id == "emb-real-1"
    assert res.explicit_embedding is True


async def test_unknown_ref_raises_model_not_found(db_session):
    client = _FakeClient(["emb-real-1"])
    await weknora_defaults.set_defaults(
        db_session,
        embedding_model_id="emb-default",
        rerank_model_id=None,
        chat_model_id="chat-default",
        multimodal_id=None,
        updated_by=None,
    )
    await db_session.commit()
    with pytest.raises(WeKnoraError) as ei:
        await sel.resolve_models_for_kb(
            db_session, client, embedding_model_ref="deadbeef", rerank_model_ref=None, trace_id=None
        )
    assert ei.value.code == "weknora_model_not_found"


async def test_falls_back_to_default(db_session):
    await weknora_defaults.set_defaults(
        db_session,
        embedding_model_id="emb-default",
        rerank_model_id=None,
        chat_model_id="chat-default",
        multimodal_id=None,
        updated_by=None,
    )
    await db_session.commit()
    client = _FakeClient(["emb-default"])
    res = await sel.resolve_models_for_kb(
        db_session, client, embedding_model_ref=None, rerank_model_ref=None, trace_id=None
    )
    assert res.embedding_model_id == "emb-default"
    assert res.chat_model_id == "chat-default"
    assert res.embedding.model_name == "embedding-emb-default"
    assert res.chat.model_name == "qwen-plus"
    assert res.explicit_embedding is False
    assert client.list_models_calls == 1


async def test_no_default_fails_closed(db_session):
    client = _FakeClient([])
    with pytest.raises(WeKnoraError) as ei:
        await sel.resolve_models_for_kb(
            db_session, client, embedding_model_ref=None, rerank_model_ref=None, trace_id=None
        )
    assert ei.value.code == "weknora_default_model_not_configured"


@pytest.mark.parametrize(
    "invalid_slot",
    ["embedding", "chat", "rerank", "multimodal"],
)
async def test_historical_invalid_default_model_family_fails_closed(db_session, invalid_slot):
    rows = _runtime_rows()
    slot_index = {"embedding": 0, "chat": 1, "rerank": 2, "multimodal": 3}
    rows[slot_index[invalid_slot]]["name"] = "random-model"

    await weknora_defaults.set_defaults(
        db_session,
        embedding_model_id="emb-default",
        rerank_model_id="rerank-default",
        chat_model_id="chat-default",
        multimodal_id="multimodal-default",
        updated_by=None,
    )
    await db_session.commit()

    client = _StaticClient(rows)
    with pytest.raises(WeKnoraError) as exc_info:
        await sel.resolve_models_for_kb(
            db_session,
            client,
            embedding_model_ref=None,
            rerank_model_ref=None,
            trace_id=None,
        )

    assert exc_info.value.code == "weknora_model_name_invalid"


async def test_explicit_ref_to_historical_invalid_model_family_fails_closed(db_session):
    from app.services.weknora_models import _model_ref

    await weknora_defaults.set_defaults(
        db_session,
        embedding_model_id="emb-default",
        rerank_model_id=None,
        chat_model_id="chat-default",
        multimodal_id=None,
        updated_by=None,
    )
    await db_session.commit()
    rows = _runtime_rows()
    rows.append(
        {
            "id": "emb-invalid",
            "name": "random-model",
            "type": "Embedding",
            "source": "remote",
        }
    )
    client = _StaticClient(rows)

    with pytest.raises(WeKnoraError) as exc_info:
        await sel.resolve_models_for_kb(
            db_session,
            client,
            embedding_model_ref=_model_ref("emb-invalid"),
            rerank_model_ref=None,
            trace_id=None,
        )

    assert exc_info.value.code == "weknora_model_name_invalid"


async def test_unselected_invalid_model_is_excluded_from_runtime_metadata(db_session):
    await weknora_defaults.set_defaults(
        db_session,
        embedding_model_id="emb-default",
        rerank_model_id=None,
        chat_model_id="chat-default",
        multimodal_id=None,
        updated_by=None,
    )
    await db_session.commit()
    rows = _runtime_rows()
    rows.append(
        {
            "id": "emb-invalid-unselected",
            "name": "random-model",
            "type": "Embedding",
            "source": "remote",
        }
    )
    client = _StaticClient(rows)

    resolved = await sel.resolve_models_for_kb(
        db_session,
        client,
        embedding_model_ref=None,
        rerank_model_ref=None,
        trace_id=None,
    )

    assert "emb-invalid-unselected" not in resolved.models_by_id

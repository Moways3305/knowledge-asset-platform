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

    async def list_models(self, *, trace_id=None):
        return [{"id": i, "name": i, "type": "Embedding"} for i in self._ids]


async def test_explicit_ref_resolves_to_real_id(db_session):
    from app.services.weknora_models import _model_ref

    client = _FakeClient(["emb-real-1"])
    ref = _model_ref("emb-real-1")
    res = await sel.resolve_models_for_kb(
        db_session, client, embedding_model_ref=ref, rerank_model_ref=None, trace_id=None
    )
    assert res.embedding_model_id == "emb-real-1"
    assert res.explicit_embedding is True


async def test_unknown_ref_raises_model_not_found(db_session):
    client = _FakeClient(["emb-real-1"])
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
        chat_model_id=None,
        multimodal_id=None,
        updated_by=None,
    )
    await db_session.commit()
    client = _FakeClient(["emb-default"])
    res = await sel.resolve_models_for_kb(
        db_session, client, embedding_model_ref=None, rerank_model_ref=None, trace_id=None
    )
    assert res.embedding_model_id == "emb-default"
    assert res.explicit_embedding is False


async def test_no_default_fails_closed(db_session):
    client = _FakeClient([])
    with pytest.raises(WeKnoraError) as ei:
        await sel.resolve_models_for_kb(
            db_session, client, embedding_model_ref=None, rerank_model_ref=None, trace_id=None
        )
    assert ei.value.code == "weknora_default_model_not_configured"

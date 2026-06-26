import pytest

from app.services import weknora_defaults

pytestmark = pytest.mark.asyncio


async def test_get_defaults_none_when_unset(db_session):
    assert await weknora_defaults.get_defaults(db_session) is None


async def test_set_defaults_upserts_singleton(db_session):
    row = await weknora_defaults.set_defaults(
        db_session,
        embedding_model_id="emb-real-1",
        rerank_model_id=None,
        chat_model_id=None,
        multimodal_id=None,
        updated_by=None,
    )
    await db_session.commit()
    assert row.default_embedding_model_id == "emb-real-1"

    await weknora_defaults.set_defaults(
        db_session,
        embedding_model_id="emb-real-2",
        rerank_model_id="rr-1",
        chat_model_id=None,
        multimodal_id=None,
        updated_by=None,
    )
    await db_session.commit()
    fetched = await weknora_defaults.get_defaults(db_session)
    assert fetched is not None
    assert fetched.id == row.id  # still a singleton, same row
    assert fetched.default_embedding_model_id == "emb-real-2"
    assert fetched.default_rerank_model_id == "rr-1"

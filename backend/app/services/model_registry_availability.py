"""Keep incomplete onboarding records out of runtime model choices."""

from sqlalchemy import select

from app.models.model_registry import RegisteredModel
from app.services.weknora_model_refs import model_ref


async def approved_knowledge_names(session):
    """Only locally journalled successful bindings may bypass legacy name-prefix rules."""
    registered = list((await session.scalars(select(RegisteredModel))).all())
    return {
        model.weknora_id: model.model_name
        for model in registered
        if model.weknora_id and model.bindings.get("knowledge", {}).get("status") == "ready"
    }


async def filter_knowledge_runtime(session, models):
    registered = list((await session.scalars(select(RegisteredModel))).all())
    by_id = {m.weknora_id: m for m in registered if m.weknora_id}
    result = []
    for raw in models:
        if not isinstance(raw, dict):
            continue
        identifier = str(raw.get("id") or "")
        model = by_id.get(identifier)
        marked = str(raw.get("description") or "").startswith("kap-registry:")
        if model is not None and model.bindings.get("knowledge", {}).get("status") != "ready":
            continue
        if marked and model is None:
            continue
        result.append(raw)
    return result


async def filter_knowledge_options(session, models):
    registered = list((await session.scalars(select(RegisteredModel))).all())
    by_ref = {model_ref(m.weknora_id): m for m in registered if m.weknora_id}
    result = []
    for item in models:
        model = by_ref.get(item.model_ref)
        marked = str(item.description or "").startswith("kap-registry:")
        if model is not None and model.bindings.get("knowledge", {}).get("status") != "ready":
            continue
        if marked and model is None:
            continue
        if marked:
            item = item.model_copy(update={"description": None})
        result.append(item)
    return result

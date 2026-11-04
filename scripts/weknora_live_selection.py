"""Read active KAP model selection. Stdout is private; runner captures it in 0600 files."""

import asyncio
import json
import logging
from sqlalchemy import text
from app.db.session import get_engine
from app.services.generation_models import _decrypt
from app.core.config import get_settings
from app.services.weknora_client import WeKnoraClient


async def collect():
    engine = get_engine()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            await conn.execute(text("SET LOCAL statement_timeout = '15s'"))
            defaults = (
                (
                    await conn.execute(
                        text(
                            "SELECT default_embedding_model_id, default_chat_model_id, "
                            "default_rerank_model_id FROM weknora_default_models"
                        )
                    )
                )
                .mappings()
                .all()
            )
            if len(defaults) != 1:
                raise RuntimeError("default selection unavailable")
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT m.provider,m.model_name,m.base_url_ciphertext,m.api_key_ciphertext "
                            "FROM content_generation_settings s JOIN content_generation_models m "
                            "ON m.id=s.default_model_id WHERE s.id=1 AND m.enabled=true "
                            "AND m.capability_type='chat'"
                        )
                    )
                )
                .mappings()
                .one()
            )
        selected = {
            slot: defaults[0]["default_" + slot + "_model_id"]
            for slot in ("embedding", "chat", "rerank")
        }
        settings = get_settings()
        client = WeKnoraClient(
            base_url=settings.weknora_base_url, api_key=settings.weknora_api_key, timeout=15
        )
        models = {str(m["id"]): m for m in await client.list_models()}
        metadata = {}
        for slot, model_id in selected.items():
            model = models[str(model_id)]
            parameters = model.get("parameters") or {}
            if isinstance(parameters, str):
                parameters = json.loads(parameters)
            metadata[slot] = {key: model[key] for key in ("name", "type", "source")}
            metadata[slot]["base_url"] = parameters.get("base_url", "")
        return {
            "selected": selected,
            "metadata": metadata,
            "generation": {
                "provider": row["provider"],
                "model": row["model_name"],
                "base_url": _decrypt(row["base_url_ciphertext"]),
                "api_key": _decrypt(row["api_key_ciphertext"]),
            },
        }
    finally:
        await engine.dispose()


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    print(json.dumps(asyncio.run(collect())))

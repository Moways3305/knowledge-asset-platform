"""Bounded offline checks inside the isolated KAP runtime; never print credentials."""

import asyncio
import base64
import json
import logging
from pathlib import Path
import sys
import time
import traceback
import uuid

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

sys.path.insert(0, "/probe/backend")

REPORT = {
    "checks": [],
    "scope": "isolated startup, stored secrets, API reads, keyword-only recall and empty test KB CRUD",
    "not_verified": [
        "live model calls",
        "vector API recall",
        "upload parsing",
        "async document deletion and reparse",
        "KAP end-to-end role authorization",
    ],
}


def check(name, passed, **facts):
    REPORT["checks"].append({"case": name, "passed": bool(passed), **facts})
    if not passed:
        raise RuntimeError("check failed: " + name)


def decrypt_values(value, key):
    count = 0
    if isinstance(value, dict):
        return sum(decrypt_values(v, key) for v in value.values())
    if isinstance(value, list):
        return sum(decrypt_values(v, key) for v in value)
    if isinstance(value, str) and value.startswith("enc:v1:"):
        encoded = value[7:]
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        plain = AESGCM(key).decrypt(raw[:12], raw[12:], None)
        if not plain:
            raise RuntimeError("empty decrypted credential")
        count = 1
    return count


async def probe(data):
    from app.services.weknora_client import WeKnoraClient, WeKnoraError

    key = data["aes_key"].encode()
    check("original_aes_key_length", len(key) == 32)
    count = decrypt_values(data["stored_records"], key)
    check("stored_secret_authenticated_decryption", count > 0, encrypted_fields=count)
    client = WeKnoraClient(base_url="http://127.0.0.1:8080", api_key=data["api_key"], timeout=30)
    async with httpx.AsyncClient(timeout=10, trust_env=False) as http:
        health = await http.get("http://127.0.0.1:8080/health")
        check(
            "application_health", health.status_code == 200 and health.json().get("status") == "ok"
        )
        denied = await http.get("http://127.0.0.1:8080/api/v1/knowledge-bases")
        check(
            "unauthenticated_request_denied",
            denied.status_code in (401, 403),
            http_status=denied.status_code,
        )
    models = await client.list_models()
    check("original_kap_key_and_model_listing", bool(models), models=len(models))
    model_rows = {row["id"]: row for row in data["stored_records"]["models"]}
    verified_fields = 0
    for model in models:
        model_id = str(model["id"])
        row = model_rows.get(model_id)
        if row is None:
            continue
        parameters = row.get("parameters") or {}
        if isinstance(parameters, str):
            parameters = json.loads(parameters)
        # Empty PUT is the upstream documented read-only credentials metadata endpoint.
        metadata = await client.get_model_credentials(model_id)
        fields = metadata.get("fields", {})
        for field in ("api_key", "app_secret"):
            if parameters.get(field):
                check(
                    "application_loaded_model_credential",
                    fields.get(field, {}).get("configured") is True,
                )
                verified_fields += 1
        await client.get_model(model_id)
    check(
        "model_credentials_visible_to_kap", verified_fields > 0, configured_fields=verified_fields
    )
    libraries = await client._call("GET", "/knowledge-bases", trace_id="isolated-api-rehearsal")
    check(
        "knowledge_base_listing",
        isinstance(libraries, list) and bool(libraries),
        libraries=len(libraries),
    )
    kb_ids = [str(item["id"]) for item in libraries]
    checked_docs = 0
    pagination = False
    for kb_id in kb_ids:
        await client.get_kb(kb_id)
        await client.get_initialization_config(kb_id)
        docs, total = await client.list_knowledge_in_kb(kb_id, page=1, page_size=2)
        check("document_page_shape", len(docs) <= 2 and total >= len(docs))
        if docs:
            detail = await client.get_knowledge(str(docs[0]["id"]))
            check("existing_document_detail", str(detail.get("id")) == str(docs[0]["id"]))
            checked_docs += 1
        if total > 2 and not pagination:
            second, second_total = await client.list_knowledge_in_kb(kb_id, page=2, page_size=2)
            check(
                "document_pagination",
                bool(second)
                and len(second) <= 2
                and total == second_total
                and not ({d["id"] for d in docs} & {d["id"] for d in second}),
            )
            pagination = True
    check("existing_data_reads", checked_docs > 0, libraries_with_documents=checked_docs)
    check("pagination_exercised", pagination)
    recalled = []
    for query in ["项目", "知识", "验收"]:
        payload = {
            "query": query,
            "knowledge_base_ids": kb_ids,
            "match_count": 5,
            "disable_vector_match": True,
            "rerank": {"enabled": False},
        }
        raw = await client._call(
            "POST", "/knowledge-search", json=payload, trace_id="isolated-keyword-rehearsal"
        )
        recalled = client._normalize_chunks(raw)
        if recalled:
            check(
                "keyword_response_normalization",
                len(recalled) <= 5 and all(r["content"] and r["knowledge_id"] for r in recalled),
            )
            chosen = recalled[0]["knowledge_id"]
            payload["knowledge_ids"] = [chosen]
            restricted = client._normalize_chunks(
                await client._call("POST", "/knowledge-search", json=payload)
            )
            check(
                "knowledge_id_search_scope",
                bool(restricted) and all(r["knowledge_id"] == chosen for r in restricted),
            )
            break
    check("keyword_recall_nonempty", bool(recalled))
    # Writes are limited to a newly created empty fixture KB in this disposable database.
    fixture = None
    try:
        embedding = next(
            (str(m["id"]) for m in models if str(m.get("type", "")).lower() == "embedding"), None
        )
        fixture = await client.create_kb(
            name="隔离接口验收-" + uuid.uuid4().hex[:8],
            embedding_model_id=embedding,
            description="虚构空库，仅用于隔离接口兼容测试",
        )
        updated_name = "隔离接口验收-已更新"
        await client.update_kb(fixture, name=updated_name)
        readback = await client.get_kb(fixture)
        check("fixture_kb_create_update_read", readback.get("name") == updated_name)
    finally:
        if fixture:
            await client.delete_kb(fixture)
    deadline = time.monotonic() + 30
    while True:
        try:
            await client.get_kb(fixture)
        except WeKnoraError as exc:
            check("fixture_kb_deleted", exc.status_code == 404, http_status=exc.status_code)
            break
        if time.monotonic() >= deadline:
            check("fixture_kb_deleted", False)
        await asyncio.sleep(1)


def main():
    logging.disable(logging.CRITICAL)
    root = Path("/evidence")
    ok = False
    try:
        data = json.loads((root / "probe-private.json").read_text())
        asyncio.run(probe(data))
        ok = True
    except Exception:
        (root / "probe-private.log").write_text(traceback.format_exc())
    REPORT["passed"] = ok
    (root / "api-report.json").write_text(json.dumps(REPORT, ensure_ascii=False, indent=2))
    print(json.dumps(REPORT, ensure_ascii=False), flush=True)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()

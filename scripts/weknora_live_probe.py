"""Synthetic-only live model and file lifecycle tests in a fresh WeKnora database."""

import asyncio
import base64
import io
import json
import logging
import os
from pathlib import Path
import secrets
import sys
import time
import traceback
from urllib.parse import urlsplit
import zipfile

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

sys.path.insert(0, "/probe/backend")
ALLOWED = {"api.deepseek.com", "dashscope.aliyuncs.com"}
REPORT = {
    "checks": [],
    "scope": "fresh synthetic database, live selected models and file lifecycle",
    "not_verified": [
        "KAP three-role end-to-end authorization",
        "multimodal model",
        "PDF/OCR pipeline",
    ],
}


def check(name, condition, **facts):
    REPORT["checks"].append({"case": name, "passed": bool(condition), **facts})
    if not condition:
        raise RuntimeError("check failed: " + name)


def endpoint_allowed(url):
    p = urlsplit(url)
    return (
        p.scheme == "https"
        and p.hostname in ALLOWED
        and p.port in (None, 443)
        and not p.username
        and not p.password
    )


def decrypt(value, key):
    if isinstance(value, dict):
        return {k: decrypt(v, key) for k, v in value.items()}
    if isinstance(value, list):
        return [decrypt(v, key) for v in value]
    if isinstance(value, str) and value.startswith("enc:v1:"):
        raw = base64.urlsafe_b64decode(value[7:] + "=" * (-len(value[7:]) % 4))
        return AESGCM(key).decrypt(raw[:12], raw[12:], None).decode()
    return value


def docx_bytes():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        )
        z.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>虚构的星舟培训项目安排在每月第二个周三，培训地点是蓝色教室。文档核对码 OFFICECHECK4826。</w:t></w:r></w:p><w:sectPr/></w:body></w:document>',
        )
    return out.getvalue()


async def ready(client, document):
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        item = await client.get_knowledge(document)
        status = item.get("parse_status")
        if status == "completed":
            return item
        check("parse_not_failed", status not in ("failed", "cancelled"), state=status)
        await asyncio.sleep(3)
    check("parse_completed_in_time", False)


async def gone(client, document):
    from app.services.weknora_client import WeKnoraError

    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            await client.get_knowledge(document)
        except WeKnoraError as exc:
            if exc.status_code == 404:
                return
            raise
        await asyncio.sleep(2)
    check("document_deletion_completed", False)


async def run(data):
    from app.services.weknora_client import WeKnoraClient
    from app.services.llm_client import LLMClient

    # Fail before credentials are used if the egress boundary is not effective.
    async with httpx.AsyncClient(timeout=5, trust_env=False) as http:
        direct_blocked = False
        try:
            await http.get("https://api.deepseek.com")
        except httpx.RequestError:
            direct_blocked = True
        check("direct_external_access_blocked", direct_blocked)
    async with httpx.AsyncClient(
        proxy=os.environ["HTTPS_PROXY"], timeout=5, trust_env=False
    ) as http:
        denied = False
        try:
            await http.get("https://example.com")
        except httpx.ProxyError as exc:
            denied = "403" in str(exc)
        check("unapproved_egress_denied", denied)

    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:8080", timeout=30, trust_env=False
    ) as http:
        username = "live-fixture-" + secrets.token_hex(4)
        credentials = {
            "username": username,
            "email": username + "@example.invalid",
            "password": secrets.token_urlsafe(18) + "A1!",
        }
        response = await http.post("/api/v1/auth/register", json=credentials)
        check("synthetic_account_created", response.status_code == 201)
        response = await http.post(
            "/api/v1/auth/login", json={k: credentials[k] for k in ("email", "password")}
        )
        check("synthetic_account_login", response.status_code == 200)
        login = response.json()
        http.headers["Authorization"] = "Bearer " + login["token"]
        response = await http.post(
            f"/api/v1/tenants/{login['active_tenant']['id']}/api-keys",
            json={"name": "synthetic-live-test", "full_access": True},
        )
        check("synthetic_key_created", response.status_code == 201)
        api_key = response.json()["data"]["token"]
    client = WeKnoraClient(base_url="http://127.0.0.1:8080", api_key=api_key, timeout=90)
    created_models = {}
    for slot in ("embedding", "chat", "rerank"):
        original = data["models"][slot]
        params = original.get("parameters") or {}
        if isinstance(params, str):
            params = json.loads(params)
        params = decrypt(params, data["aes_key"].encode())
        check("model_endpoint_allowed", endpoint_allowed(params.get("base_url", "")), usage=slot)
        model = await client.create_model(
            payload={
                "name": original["name"],
                "type": original["type"],
                "source": original["source"],
                "parameters": params,
            }
        )
        model_id = str(model["id"])
        created_models[slot] = model_id
        kwargs = {
            "model_id": model_id,
            "model_name": original["name"],
            "base_url": params["base_url"],
            "source": original["source"],
            "provider": params.get("provider"),
            "interface_type": params.get("interface_type"),
        }
        method = {
            "embedding": client.test_embedding_model,
            "chat": client.check_remote_model,
            "rerank": client.check_rerank_model,
        }[slot]
        result = await method(**kwargs)
        check("live_" + slot + "_model", result.get("available") is True)
        if slot == "embedding":
            check(
                "embedding_vector_dimension",
                int(result.get("dimension", 0)) > 0,
                dimension=result.get("dimension"),
            )

    kb = await client.create_kb(
        name="虚构资料联网验收",
        embedding_model_id=created_models["embedding"],
        description="仅虚构样本，不含生产资料",
    )
    # Exercise the actual KAP initialization endpoint, referencing saved models.
    await client.update_initialization_config(
        kb,
        config={
            "llmModelId": created_models["chat"],
            "embeddingModelId": created_models["embedding"],
            "documentSplitting": {
                "chunkSize": 512,
                "chunkOverlap": 64,
                "separators": ["\n\n", "\n", "。"],
            },
            "storageProvider": "local",
            "multimodal": {"enabled": False},
            "vlm_config": {"enabled": False},
            "questionGeneration": {"enabled": False, "questionCount": 3},
            "nodeExtract": {"enabled": False},
        },
    )
    initialized = await client.get_kb(kb)
    check(
        "kap_kb_initialization_readback",
        initialized.get("embedding_model_id") == created_models["embedding"]
        and initialized.get("summary_model_id") == created_models["chat"],
    )
    old_code, new_code = "KAPOLDMARK7391", "KAPNEWMARK8624"

    def markdown(code):
        return (
            "# 虚构设备资料\n星舟设备的定期检修间隔为17天。每次由两名工程师共同完成检查。\n核对码："
            + code
            + "\n"
        ).encode()

    first = await client.upload_file(
        kb_id=kb,
        content=markdown(old_code),
        file_name="synthetic-maintenance.md",
        mime="text/markdown",
    )
    doc = str(first["id"])
    await ready(client, doc)
    check("markdown_upload_and_parse", True)
    office = await client.upload_file(
        kb_id=kb,
        content=docx_bytes(),
        file_name="synthetic-training.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    office_id = str(office["id"])
    await ready(client, office_id)
    chunks = await client.search(
        query="OFFICECHECK4826", kb_ids=[kb], knowledge_ids=[office_id], keyword_only=True
    )
    check("docx_parse_and_recall", any("OFFICECHECK4826" in c["content"] for c in chunks))

    raw = await client._call(
        "POST",
        f"/knowledge-bases/{kb}/hybrid-search",
        json={
            "query_text": "两次例行检修之间隔多少日？",
            "match_count": 5,
            "disable_keywords_match": True,
            "disable_vector_match": False,
            "vector_threshold": 0,
            "knowledge_ids": [doc],
        },
    )
    rows = raw if isinstance(raw, list) else raw.get("results", [])
    check(
        "vector_only_recall",
        bool(rows)
        and all(r.get("match_type") == 0 for r in rows)
        and any(old_code in r.get("content", "") for r in rows),
    )
    context = "\n".join(c["content"] for c in client._normalize_chunks(raw))
    generation = data["generation"]
    check("generation_endpoint_allowed", endpoint_allowed(generation["base_url"]))
    llm = LLMClient(**generation, timeout=90)
    answer = await llm.chat_completion(
        [
            {
                "role": "system",
                "content": "只根据资料回答，输出JSON对象，字段interval_days为整数，source_code为原文核对码。",
            },
            {"role": "user", "content": context + "\n问题：检修相隔多少天？"},
        ],
        max_tokens=200,
        max_input_chars=5000,
    )
    parsed = json.loads(answer)
    check(
        "kap_generation_with_retrieved_evidence",
        parsed.get("interval_days") == 17 and parsed.get("source_code") == old_code,
    )

    replacement = await client.reparse_knowledge(
        kb_id=kb,
        knowledge_id=doc,
        content=markdown(new_code),
        file_name="synthetic-maintenance.md",
        mime="text/markdown",
    )
    next_id = str(replacement["id"])
    await ready(client, next_id)
    await gone(client, doc)
    latest = await client.search(
        query=new_code, kb_ids=[kb], knowledge_ids=[next_id], keyword_only=True
    )
    old = await client.search(query=old_code, kb_ids=[kb], keyword_only=True)
    check(
        "reparse_new_content_visible_old_content_absent",
        any(new_code in c["content"] for c in latest)
        and all(old_code not in c["content"] and c["knowledge_id"] != doc for c in old),
    )
    for document in (next_id, office_id):
        await client.delete_knowledge(document)
        await gone(client, document)
    remaining, total = await client.list_knowledge_in_kb(kb)
    check("async_delete_completed", not remaining and total == 0)
    check("deleted_content_not_recalled", not await client.search(query="星舟", kb_ids=[kb]))
    await client.delete_kb(kb)


def main():
    logging.disable(logging.CRITICAL)
    root = Path("/evidence")
    ok = False
    try:
        asyncio.run(run(json.loads((root / "live-private.json").read_text())))
        ok = True
    except Exception:
        (root / "probe-private.log").write_text(traceback.format_exc())
    REPORT["passed"] = ok
    (root / "live-report.json").write_text(json.dumps(REPORT, ensure_ascii=False, indent=2))
    print(json.dumps(REPORT, ensure_ascii=False), flush=True)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()

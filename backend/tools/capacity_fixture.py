"""HTTP stand-ins, NOT a WeKnora/model performance benchmark.

Every supported operation has counters. Unknown routes fail, rather than returning
fake success. No real model credentials, external requests or business data.
"""

import asyncio
import hashlib
import json
import time
from collections import Counter

import uvicorn
from capacity_common import guard
from fastapi import FastAPI, HTTPException, Request
from starlette.responses import Response

guard()
app = FastAPI()
counts = Counter()
inflight = Counter()
peak = Counter()
settings = {"llm_delay": 0.05, "search_delay": 0.05}
docs = {}
kbs = {}


async def delay(request, kind, seconds):
    """Observe socket closure, not a guarantee that real providers stop computing."""
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if await request.is_disconnected():
            counts[kind + "_disconnected"] += 1
            return False
        await asyncio.sleep(min(0.05, max(0, until - time.monotonic())))
    return True


def wrap(value):
    return {"success": True, "data": value}


@app.get("/control")
async def stats():
    return {"counts": counts, "inflight": inflight, "peak": peak, "settings": settings}


@app.post("/control")
async def control(request: Request):
    body = await request.json()
    for key in settings:
        if key in body:
            settings[key] = max(0, min(45, float(body[key])))
    return await stats()


@app.post("/seed")
async def seed(request: Request):
    body = await request.json()
    docs.update({row["id"]: row for row in body["docs"]})
    kbs.update({row["id"]: row for row in body["kbs"]})
    return {"documents": len(docs)}


@app.post("/v1/chat/completions")
async def llm(request: Request):
    body = await request.json()
    system = body["messages"][0].get("content", "")
    kind = (
        "planning" if '"queries"' in system else "answer" if "answer_parts" in system else "content"
    )
    counts[kind] += 1
    inflight[kind] += 1
    peak[kind] = max(peak[kind], inflight[kind])
    try:
        if not await delay(request, kind, settings["llm_delay"]):
            return Response(status_code=499)
        value = (
            {"queries": []}
            if kind == "planning"
            else {
                "status": "answered",
                "answer_parts": [
                    {"text": "Synthetic capacity benchmark answer.", "citation_orders": [1]}
                ],
            }
            if kind == "answer"
            else {
                "topic": "Capacity synthetic document",
                "one_liner": "Synthetic capacity material",
                "detailed": "Synthetic content used for isolated capacity testing.",
                "key_points": ["Synthetic"],
                "tags": ["capacity"],
                "confidentiality_level": "L2",
                "confidentiality_confidence": "high",
                "version": "V1",
                "version_confidence": "high",
                "inferred_fields": [],
            }
        )
        return {"choices": [{"message": {"content": json.dumps(value)}}]}
    finally:
        inflight[kind] -= 1


@app.get("/api/v1/models")
async def models():
    counts["models"] += 1
    return wrap(
        [
            {
                "id": "capacity-embedding",
                "name": "text-embedding-v3",
                "type": "Embedding",
                "is_enabled": True,
                "source": "remote",
            },
            {
                "id": "capacity-chat",
                "name": "deepseek-chat",
                "type": "KnowledgeQA",
                "is_enabled": True,
                "source": "remote",
            },
        ]
    )


@app.get("/api/v1/knowledge/batch")
async def batch(request: Request):
    counts["batch"] += 1
    return wrap([docs[key] for key in request.query_params.getlist("ids") if key in docs])


@app.post("/api/v1/knowledge-search")
async def search(request: Request):
    counts["search"] += 1
    body = await request.json()
    inflight["search"] += 1
    peak["search"] = max(peak["search"], inflight["search"])
    try:
        if not await delay(request, "search", settings["search_delay"]):
            return Response(status_code=499)
    finally:
        inflight["search"] -= 1
    allowed = set(body.get("knowledge_base_ids", []))
    ids = body.get("knowledge_ids")
    matches = [
        row
        for row in docs.values()
        if (row["id"] in ids if ids is not None else row["knowledge_base_id"] in allowed)
    ]
    return wrap(
        [
            {
                "knowledge_id": row["id"],
                "content": "Capacity synthetic benchmark text",
                "score": 0.9,
                "chunk_index": 0,
            }
            for row in matches[: body.get("match_count", 20)]
        ]
    )


@app.get("/api/v1/knowledge/{doc_id}")
async def get_doc(doc_id: str):
    if doc_id not in docs:
        raise HTTPException(404)
    return wrap(docs[doc_id])


@app.delete("/api/v1/knowledge/{doc_id}")
async def delete_doc(doc_id: str):
    docs.pop(doc_id, None)
    counts["delete"] += 1
    return wrap({})


@app.post("/api/v1/knowledge-bases/{kb_id}/knowledge/file")
async def upload(kb_id: str, request: Request):
    form = await request.form()
    content = await form["file"].read()
    key = hashlib.sha256(kb_id.encode() + content).hexdigest()
    counts["upload"] += 1
    docs[key] = {
        "id": key,
        "knowledge_base_id": kb_id,
        "parse_status": "completed",
        "file_hash": hashlib.sha256(content).hexdigest(),
    }
    return wrap(docs[key])


@app.get("/api/v1/knowledge-bases/{kb_id}/knowledge")
async def list_docs(kb_id: str):
    rows = [row for row in docs.values() if row["knowledge_base_id"] == kb_id]
    return {**wrap(rows), "total": len(rows)}


@app.get("/api/v1/knowledge-bases/{kb_id}")
@app.get("/api/v1/initialization/config/{kb_id}")
async def kb(kb_id: str):
    if kb_id not in kbs:
        raise HTTPException(404)
    return wrap(kbs[kb_id])


@app.put("/api/v1/initialization/config/{kb_id}")
async def update_kb(kb_id: str, request: Request):
    kbs[kb_id].update(await request.json())
    return wrap(kbs[kb_id])


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000, access_log=False, log_level="warning")

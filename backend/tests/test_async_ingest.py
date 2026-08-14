"""异步入库 confirm 前置校验 + worker loop-local engine + 共享存储编排。

- confirm 在 processing 任务上 → 409 ingest_processing_not_ready。
- 空摘要 confirm → 422 ingest_summary_required；空标题 → 422 ingest_title_required。
- 抽取失败任务 + 人工补全摘要 → 可 confirm（不静默写空摘要）。
- worker `run_task` 每次自建 loop-local engine，多次 asyncio.run 不复用关闭的循环。
- docker-compose：backend 与 worker 共享同一 upload_storage 卷与 STORAGE_ROOT。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from app.seed.dev_seed import USER_CONSULTANT

UPLOAD = "/api/v1/ingest/upload"
_TXT = "异步入库测试\n标题行\n正文若干。".encode()
_BLANK = b"   \n  \t "  # 抽取为空 → status failed


def _hdr(user_id):
    return {"X-Dev-User-Id": str(user_id)}


def _confirm_body(**over):
    base = {
        "title": "异步资产",
        "summary": "确认摘要",
        "tags": ["t"],
        "target_scope": "personal",
        "confidentiality_level": "L2",
        "directory_key": "personal.learning_notes",
    }
    base.update(over)
    return base


# ---------------- confirm 前置校验 ----------------
async def test_confirm_processing_not_ready(client, db_session, monkeypatch):
    import app.services.ingest as ingest_mod

    async def fake_enqueue(session, task_id, *, storage, llm, desensitizer, trace_id):
        return "processing"  # 模拟异步：保持 processing，不内联处理

    monkeypatch.setattr(ingest_mod, "enqueue_ingest_processing", fake_enqueue)
    up = await client.post(
        UPLOAD, headers=_hdr(USER_CONSULTANT), files={"file": ("d.txt", _TXT, "text/plain")}
    )
    task_id = up.json()["ingest_task_id"]
    assert up.json()["status"] == "processing"
    # 仍 processing 时 confirm → 409。
    r = await client.post(
        f"/api/v1/ingest/{task_id}/confirm", headers=_hdr(USER_CONSULTANT), json=_confirm_body()
    )
    assert r.status_code == 409
    assert r.json()["detail"]["denied_reason"] == "ingest_processing_not_ready"
    # 不泄露内部引用。
    for tok in ("source_file_ref", "storage_ref", "/data/uploads", "weknora", "sk-"):
        assert tok not in r.text


async def test_confirm_empty_summary_rejected(client):
    up = await client.post(
        UPLOAD, headers=_hdr(USER_CONSULTANT), files={"file": ("d.txt", _TXT, "text/plain")}
    )
    task_id = up.json()["ingest_task_id"]
    # 空摘要 + 空一句话 → 422 ingest_summary_required。
    r = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_confirm_body(summary="", one_liner=""),
    )
    assert r.status_code == 422
    assert r.json()["detail"]["denied_reason"] == "ingest_summary_required"


async def test_confirm_empty_title_rejected(client):
    up = await client.post(
        UPLOAD, headers=_hdr(USER_CONSULTANT), files={"file": ("d.txt", _TXT, "text/plain")}
    )
    task_id = up.json()["ingest_task_id"]
    r = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_confirm_body(title="   "),
    )
    assert r.status_code == 422
    assert r.json()["detail"]["denied_reason"] == "ingest_title_required"


async def test_confirm_one_liner_only_ok(client):
    up = await client.post(
        UPLOAD, headers=_hdr(USER_CONSULTANT), files={"file": ("d.txt", _TXT, "text/plain")}
    )
    task_id = up.json()["ingest_task_id"]
    # 仅一句话摘要（无详细摘要）也可确认（不再静默写"（无摘要）"）。
    r = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_confirm_body(summary="", one_liner="一句话摘要即可"),
    )
    assert r.status_code == 200, r.text


async def test_confirm_persists_reviewed_ai_fields_exactly(client):
    up = await client.post(
        UPLOAD,
        headers=_hdr(USER_CONSULTANT),
        files={"file": ("reviewed.txt", _TXT, "text/plain")},
    )
    task_id = up.json()["ingest_task_id"]
    confirmed = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_confirm_body(
            title="人工核对标题",
            one_liner="人工核对一句话",
            summary="人工核对详细摘要",
            key_points=["人工知识点一", "人工知识点二"],
            tags=["人工标签", "复核完成"],
        ),
    )
    assert confirmed.status_code == 200, confirmed.text

    detail = await client.get(
        f"/api/v1/knowledge/{confirmed.json()['result_asset_id']}",
        headers=_hdr(USER_CONSULTANT),
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["title"] == "人工核对标题"
    assert body["summary"]["one_liner"] == "人工核对一句话"
    assert body["summary"]["detailed"] == "人工核对详细摘要"
    assert body["summary"]["key_points"] == ["人工知识点一", "人工知识点二"]
    assert set(body["tags"]) == {"人工标签", "复核完成"}


async def test_failed_task_with_manual_summary_cannot_bypass_markdown_generation(client):
    # 空白文件 → 抽取为空 → status failed。
    up = await client.post(
        UPLOAD, headers=_hdr(USER_CONSULTANT), files={"file": ("blank.txt", _BLANK, "text/plain")}
    )
    task_id = up.json()["ingest_task_id"]
    assert up.json()["status"] == "failed"
    # 人工补全元数据不能绕过规范 Markdown 缺失。
    r = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=_hdr(USER_CONSULTANT),
        json=_confirm_body(title="人工补全标题", summary="人工补全的详细摘要"),
    )
    assert r.status_code == 409
    assert r.json()["detail"]["denied_reason"] == "canonical_markdown_not_ready"


# ---------------- worker loop-local engine ----------------
def test_run_task_loop_local_engine_reentrant(monkeypatch, tmp_path):
    """run_task 多次调用各自新建 engine/loop，不复用已关闭循环（asyncpg 问题的回归守卫）。"""
    import app.worker.runtime as rt

    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'wk.db').as_posix()}"

    class _FakeSettings:
        database_url = db_url
        db_pool_size = 5
        db_max_overflow = 10
        db_pool_recycle = 3600

    monkeypatch.setattr(rt, "get_settings", lambda: _FakeSettings())

    async def _probe(maker):
        async with maker() as s:
            return (await s.execute(text("SELECT 1"))).scalar()

    # 两次独立 asyncio.run：旧的全局 lru_cache engine 会在第二次因循环亲和性崩溃。
    assert rt.run_task(_probe) == 1
    assert rt.run_task(_probe) == 1


# ---------------- 共享存储编排 ----------------
def test_compose_backend_worker_share_upload_storage():
    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    # backend 与 worker 都挂载同一命名卷到同一路径。
    assert compose.count("upload_storage:/data/uploads") >= 2
    assert "STORAGE_ROOT: /data/uploads" in compose
    # 顶层声明该卷。
    assert "\n  upload_storage:" in compose


async def test_no_leak_ai_result_processing_state(client, db_session, monkeypatch):
    """processing 态 ai-result 不伪装成功、不泄露内部引用。"""
    import app.services.ingest as ingest_mod

    async def fake_enqueue(session, task_id, *, storage, llm, desensitizer, trace_id):
        return "processing"

    monkeypatch.setattr(ingest_mod, "enqueue_ingest_processing", fake_enqueue)
    up = await client.post(
        UPLOAD, headers=_hdr(USER_CONSULTANT), files={"file": ("d.txt", _TXT, "text/plain")}
    )
    task_id = up.json()["ingest_task_id"]
    ai = await client.get(f"/api/v1/ingest/{task_id}/ai-result", headers=_hdr(USER_CONSULTANT))
    body = ai.json()
    assert body["status"] == "processing"
    assert body["content_processing_status"] == "processing"
    assert body.get("suggested_title") is None  # 未完成 → 不伪装成功
    for tok in ("source_file_ref", "storage_ref", "/data/uploads", "weknora", "sk-"):
        assert tok not in ai.text

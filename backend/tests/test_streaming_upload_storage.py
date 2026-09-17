import asyncio
import hashlib
import threading

import pytest

from app.services.storage import LocalFileStorage, StorageError, UploadTooLarge


async def test_upload_chunks_and_hash(tmp_path):
    storage = LocalFileStorage(tmp_path)
    content = b"abc" * 900000
    position = 0
    reads = []

    async def read(size):
        nonlocal position
        reads.append(size)
        chunk = content[position : position + size]
        position += len(chunk)
        return chunk

    stored = await storage.save_upload(read, original_name="../资料.doc")
    assert stored.size == len(content)
    assert stored.sha256 == hashlib.sha256(content).hexdigest()
    assert storage.resolve_path(stored.ref).read_bytes() == content
    assert max(reads) <= 1024 * 1024
    assert len(reads) >= 4


@pytest.mark.parametrize("content", [b"", b"abcde"])
async def test_upload_empty_and_exact_limit(tmp_path, content):
    remaining = content

    async def read(size):
        nonlocal remaining
        chunk, remaining = remaining[:size], remaining[size:]
        return chunk

    storage = LocalFileStorage(tmp_path)
    stored = await storage.save_upload(read, original_name="test.txt", max_bytes=5)
    assert stored.size == len(content)
    assert stored.sha256 == hashlib.sha256(content).hexdigest()


async def test_upload_disk_failure_is_safe_and_cleans_partial(tmp_path, monkeypatch):
    from pathlib import Path

    original_open = Path.open
    calls = 0

    def failing_open(path, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("private disk path")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)

    async def read(size):
        return b"abc"

    with pytest.raises(StorageError, match="^storage_failed$"):
        await LocalFileStorage(tmp_path).save_upload(read, original_name="test.pdf")
    assert not list(tmp_path.rglob("*.pdf"))


@pytest.mark.parametrize("failure", ["oversize", "timeout", "read_error", "cancel"])
async def test_upload_removes_partial_file(tmp_path, failure):
    storage = LocalFileStorage(tmp_path)
    calls = 0

    async def read(size):
        nonlocal calls
        calls += 1
        if calls == 1:
            return b"abc"
        if failure == "timeout":
            await asyncio.sleep(10)
        if failure == "cancel":
            raise asyncio.CancelledError
        if failure == "read_error":
            raise OSError("unreadable")
        return b"def"

    expected = {
        "oversize": UploadTooLarge,
        "timeout": asyncio.TimeoutError,
        "read_error": OSError,
        "cancel": asyncio.CancelledError,
    }[failure]
    with pytest.raises(expected):
        await storage.save_upload(read, original_name="test.pdf", max_bytes=5, timeout=0.1)
    assert not list(tmp_path.rglob("*.*"))


async def test_cancel_waits_for_disk_write_before_cleanup(tmp_path, monkeypatch):
    from pathlib import Path

    storage = LocalFileStorage(tmp_path)
    started = threading.Event()
    release = threading.Event()
    original_open = Path.open

    def slow_open(path, *args, **kwargs):
        if args and args[0] == "xb":
            started.set()
            assert release.wait(5)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", slow_open)

    async def read(size):
        return b"abc"

    task = asyncio.create_task(storage.save_upload(read, original_name="slow.pdf"))
    assert await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not list(tmp_path.rglob("*.pdf"))

"""Admission must precede file I/O and release locks on every exit path."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services import ingest_capacity


class Gate:
    def __init__(self, answers, name="sample.pptx"):
        self.scalar = AsyncMock(side_effect=answers)
        self.rollback = AsyncMock()
        self.get = AsyncMock(
            return_value=SimpleNamespace(
                cancel_requested=False,
                status="processing",
                processing_stage="text_extraction",
                source_file_name=name,
            )
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))


@pytest.mark.asyncio
async def test_capacity_denial_does_not_enter_heavy_pool(monkeypatch):
    monkeypatch.setattr(
        ingest_capacity,
        "get_settings",
        lambda: SimpleNamespace(ingest_processing_window=2, ingest_heavy_processing_window=1),
    )
    gate = Gate([False, False])
    async with ingest_capacity.processing_slot(lambda: gate, uuid4()) as admitted:
        assert not admitted
    assert gate.scalar.await_count == 2
    gate.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_heavy_capacity_denial_releases_general_slot(monkeypatch):
    monkeypatch.setattr(
        ingest_capacity,
        "get_settings",
        lambda: SimpleNamespace(ingest_processing_window=2, ingest_heavy_processing_window=1),
    )
    gate = Gate([True, False])
    async with ingest_capacity.processing_slot(lambda: gate, uuid4()) as admitted:
        assert not admitted
    gate.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_exception_releases_all_slots():
    gate = Gate([True, True])
    with pytest.raises(RuntimeError, match="parser stopped"):
        async with ingest_capacity.processing_slot(lambda: gate, uuid4()) as admitted:
            assert admitted
            raise RuntimeError("parser stopped")
    gate.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_text_does_not_take_heavy_slot():
    gate = Gate([True], name="notes.md")
    async with ingest_capacity.processing_slot(lambda: gate, uuid4()) as admitted:
        assert admitted
    assert gate.scalar.await_count == 1
    gate.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancellation_is_not_blocked_by_capacity():
    gate = Gate([])
    gate.get.return_value.cancel_requested = True
    async with ingest_capacity.processing_slot(lambda: gate, uuid4()) as admitted:
        assert admitted
    gate.scalar.assert_not_awaited()
    gate.rollback.assert_awaited_once()

import io
from contextlib import asynccontextmanager

import httpx
import pytest
from PIL import Image

from app.services.weknora_client import WeKnoraClient


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (
            200,
            {
                "success": True,
                "data": {
                    "ok": True,
                    "raw_response": "SECRET-ANSWER",
                    "request": {"url": "SECRET-URL"},
                },
            },
            {"available": True},
        ),
        (
            200,
            {
                "success": True,
                "data": {"ok": False, "raw_response": "SECRET", "error": "SECRET-KEY"},
            },
            {"available": False},
        ),
        (200, {"success": True, "data": {"ok": True, "raw_response": ""}}, {"available": False}),
        (
            200,
            {"success": True, "data": {"ok": True, "raw_response": "text", "error": "failed"}},
            {"available": False},
        ),
        (
            200,
            {"success": False, "data": {"ok": True, "raw_response": "text"}},
            {"available": False},
        ),
        (
            200,
            {"success": True, "data": {"ok": True, "raw_response": {"content": "text"}}},
            {"available": False},
        ),
        (404, {"error": "SECRET"}, {"available": False, "error_code": "vision_test_unavailable"}),
        (405, {}, {"available": False, "error_code": "vision_test_unavailable"}),
        (403, {"error": "SECRET"}, {"available": False}),
        (307, {}, {"available": False}),
    ],
)
async def test_native_vision_contract_and_no_private_preview(monkeypatch, status, body, expected):
    calls = []

    def handle(request):
        calls.append(request)
        assert request.method == "POST"
        assert request.url.path == "/api/v1/models/saved-id/debug"
        assert request.headers["X-API-Key"] == "sk-platform-only"
        assert request.headers["X-Request-ID"] == "safe-trace"
        assert b"synthetic-vision.png" in request.content
        assert b"api_key" not in request.content
        assert b"base_url" not in request.content
        assert b"Describe the main shape" in request.content
        return httpx.Response(
            status, json=body, headers={"Location": "https://must-not-follow.invalid"}
        )

    @asynccontextmanager
    async def pool(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            yield client

    monkeypatch.setattr("app.services.weknora_client.pooled_http_client", pool)
    client = WeKnoraClient(base_url="http://wk", api_key="sk-platform-only")
    assert await client.check_vision_model(model_id="saved-id", trace_id="safe-trace") == expected
    assert len(calls) == 1


@pytest.mark.parametrize("response", ["timeout", "network", "invalid_json", "oversized"])
async def test_vision_transport_failures_are_bounded_and_safe(monkeypatch, response):
    def handle(request):
        if response == "timeout":
            raise httpx.ReadTimeout("SECRET-KEY")
        if response == "network":
            raise httpx.ConnectError("SECRET-HOST")
        return httpx.Response(
            200, content=b"SECRET" if response == "invalid_json" else b"a" * (1024 * 1024 + 1)
        )

    @asynccontextmanager
    async def pool(**kwargs):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            yield client

    monkeypatch.setattr("app.services.weknora_client.pooled_http_client", pool)
    result = await WeKnoraClient(base_url="http://wk", api_key="sk-test").check_vision_model(
        model_id="id"
    )
    assert result == (
        {"available": False, "error_code": "model_test_timeout"}
        if response == "timeout"
        else {"available": False}
    )


def test_synthetic_fixture_is_a_valid_image_without_external_files():
    from app.services.vision_check import synthetic_image

    image = Image.open(io.BytesIO(synthetic_image()))
    assert image.size == (64, 64)
    assert image.getpixel((0, 0)) == (255, 255, 255)
    assert image.getpixel((32, 32)) == (255, 0, 0)

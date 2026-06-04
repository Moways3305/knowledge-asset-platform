"""Tests for the /health endpoint and trace_id middleware.

These tests do not require a database — /health is liveness-only.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "service" in body
    assert "environment" in body
    assert body["trace_id"]


def test_health_generates_trace_id_header():
    resp = client.get("/health")
    assert resp.headers.get("X-Trace-Id")


def test_health_reuses_inbound_trace_id():
    inbound = "test-trace-123"
    resp = client.get("/health", headers={"X-Trace-Id": inbound})
    assert resp.headers.get("X-Trace-Id") == inbound
    assert resp.json()["trace_id"] == inbound

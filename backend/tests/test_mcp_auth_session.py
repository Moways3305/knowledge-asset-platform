"""Frozen OAuth errors must propagate unchanged on Python 3.10 and 3.12."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from mcp.server.auth.provider import TokenError

from app.db.session import get_db
from app.services import mcp_auth


async def test_override_session_closes_and_preserves_frozen_oauth_error():
    app = FastAPI()
    session = object()
    events = []

    async def override():
        try:
            yield session
        finally:
            events.append("closed")

    app.dependency_overrides[get_db] = override
    error = TokenError("invalid_grant", "Grant revoked")
    with pytest.raises(TokenError) as caught:
        async with mcp_auth._database_session(app) as acquired:
            assert acquired is session
            raise error
    assert caught.value is error
    assert events == ["closed"]


async def test_default_session_closes_and_preserves_frozen_oauth_error(monkeypatch):
    session = AsyncMock()
    session.__aenter__.return_value = session
    monkeypatch.setattr(mcp_auth, "get_sessionmaker", lambda: lambda: session)
    error = TokenError("invalid_grant", "User no longer eligible")
    with pytest.raises(TokenError) as caught:
        async with mcp_auth._database_session(FastAPI()) as acquired:
            assert acquired is session
            raise error
    assert caught.value is error
    session.__aexit__.assert_awaited_once()
    args = session.__aexit__.await_args.args
    assert args[0] is TokenError and args[1] is error


async def test_override_session_closes_on_normal_return():
    app = FastAPI()
    events = []

    async def override():
        try:
            yield "session"
        finally:
            events.append("closed")

    app.dependency_overrides[get_db] = override
    async with mcp_auth._database_session(app) as session:
        assert session == "session"
    assert events == ["closed"]

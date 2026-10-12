"""Shared MCP verification and session factory; no protocol dependency."""

from datetime import timezone
from typing import Any

from fastapi import FastAPI
from mcp.server.auth.provider import AccessToken

from app.db.session import get_db, get_sessionmaker
from app.services import agent_registry
from app.services import external_agent_gateway as gateway


class _DatabaseSession:
    """Do not use a generator context manager around frozen SDK exceptions.

    Python 3.12 contextlib assigns exception.__traceback__ while propagating an
    exception out of an async generator. Frozen OAuth errors reject that write.
    A class-based manager closes the session without mutating the exception.
    """

    def __init__(self, kap_app: FastAPI):
        self._app = kap_app
        self._generator: Any = None
        self._session: Any = None

    async def __aenter__(self):
        override = self._app.dependency_overrides.get(get_db)
        if override is not None:
            self._generator = override()
            self._session = await anext(self._generator)
            return self._session
        self._session = get_sessionmaker()()
        return await self._session.__aenter__()

    async def __aexit__(self, exc_type, exc, traceback):
        if self._generator is not None:
            await self._generator.aclose()
        else:
            await self._session.__aexit__(exc_type, exc, traceback)
        return False


def _database_session(kap_app: FastAPI) -> _DatabaseSession:
    return _DatabaseSession(kap_app)


class _KapTokenVerifier:
    def __init__(self, kap_app: FastAPI) -> None:
        self._kap_app = kap_app

    async def verify_token(self, token: str) -> AccessToken | None:
        async with _database_session(self._kap_app) as session:
            rule = await agent_registry.lookup_enabled_rule(session, token)
            if (
                rule is None
                or rule.provider != "workbuddy"
                or rule.capability not in {"qa", "qa_operations"}
                or rule.bound_user_id is None
            ):
                return None
            caller = await gateway.resolve_caller(session, rule.bound_user_id)
            if caller is None or not caller.is_business_user:
                return None
            expires_at = rule.token_expires_at
            expires_epoch = None
            if expires_at is not None:
                aware = expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
                expires_epoch = int(aware.timestamp())
            return AccessToken(
                token=token,
                client_id=f"workbuddy:{rule.id}",
                scopes=["qa"],
                expires_at=expires_epoch,
            )

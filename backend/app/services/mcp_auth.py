"""Shared MCP verification and session factory; no protocol dependency."""

from contextlib import asynccontextmanager
from datetime import timezone

from fastapi import FastAPI
from mcp.server.auth.provider import AccessToken

from app.db.session import get_db, get_sessionmaker
from app.services import agent_registry
from app.services import external_agent_gateway as gateway


@asynccontextmanager
async def _database_session(kap_app: FastAPI):
    override = kap_app.dependency_overrides.get(get_db)
    if override is not None:
        generator = override()
        session = await anext(generator)
        try:
            yield session
        finally:
            await generator.aclose()
        return
    async with get_sessionmaker()() as session:
        yield session


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

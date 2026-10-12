"""SDK protocol validation + durable, user-consented OAuth grants.

No token exchange proxies, no arbitrary URL fetches, no implicit write consent.
Access tokens use the existing registry and gateway's live user permissions.
"""

import secrets
import uuid
from datetime import timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from sqlalchemy import delete, func, select, text

from app.core.config import get_settings
from app.db.utils import utc_now
from app.models.agent_registry import AgentWhitelistRule
from app.models.mcp_oauth import McpOAuthRecord
from app.schemas.enums import AuditLogType
from app.services import agent_registry
from app.services import audit as audit_service
from app.services import external_agent_gateway as gateway


def digest(value):
    return agent_registry.hash_token(value)


def aware(value):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def callback(uri, **values):
    parsed = urlsplit(uri)
    return urlunsplit(
        parsed._replace(
            query=urlencode(
                [(key, value) for key, value in parse_qsl(parsed.query) if key not in values]
                + [(key, value) for key, value in values.items() if value is not None]
            )
        )
    )


class KapOAuthProvider:
    def __init__(self, app, origin):
        self.app, self.origin = app, origin.rstrip("/")
        self.resource = self.origin + "/mcp"

    def session(self):
        from app.services.mcp_auth import _database_session

        return _database_session(self.app)

    def cipher(self):
        key = get_settings().mcp_oauth_client_encryption_key
        try:
            return Fernet(key.encode("ascii"))
        except (ValueError, UnicodeError):
            raise HTTPException(503, detail={"message": "OAuth 客户端加密密钥未安全配置"}) from None

    async def record(self, session, key, kind, *, lock=False):
        query = select(McpOAuthRecord).where(McpOAuthRecord.key == key, McpOAuthRecord.kind == kind)
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        row = await session.scalar(query)
        return row if row and aware(row.expires_at) > utc_now() else None

    async def bound_records(self, session, kind, maximum):
        # Serialize quota checks across PostgreSQL workers. SQLite tests run
        # serially; production does not rely on process-local counters.
        if session.get_bind().dialect.name == "postgresql":
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:quota))"),
                {"quota": "kap-mcp-oauth-" + kind},
            )
        await session.execute(delete(McpOAuthRecord).where(McpOAuthRecord.expires_at <= utc_now()))
        count = await session.scalar(
            select(func.count()).select_from(McpOAuthRecord).where(McpOAuthRecord.kind == kind)
        )
        return count < maximum

    async def get_client(self, client_id):
        async with self.session() as session:
            row = await self.record(session, digest(client_id), "client")
            if not row:
                return None
            data = dict(row.payload)
            encrypted = data.pop("encrypted_secret", None)
            if encrypted:
                try:
                    data["client_secret"] = self.cipher().decrypt(encrypted.encode()).decode()
                except InvalidToken:
                    return None
            return OAuthClientInformationFull.model_validate(data)

    async def register_client(self, client_info):
        if len(client_info.redirect_uris) > 8:
            raise RegistrationError("invalid_redirect_uri", "Too many redirects")
        for uri in client_info.redirect_uris:
            parsed = urlsplit(str(uri))
            if (
                len(str(uri)) > 2048
                or not parsed.hostname
                or parsed.fragment
                or parsed.username
                or parsed.password
                or (
                    parsed.scheme != "https"
                    and not (
                        parsed.scheme == "http"
                        and parsed.hostname in {"127.0.0.1", "::1", "localhost"}
                    )
                )
            ):
                raise RegistrationError(
                    "invalid_redirect_uri", "HTTPS or loopback redirect required"
                )
        if client_info.client_name and len(client_info.client_name) > 200:
            raise RegistrationError("invalid_client_metadata", "Client name too long")
        data = client_info.model_dump(mode="json")
        secret = data.pop("client_secret", None)
        if secret:
            data["encrypted_secret"] = self.cipher().encrypt(secret.encode()).decode()
        async with self.session() as session:
            if not await self.bound_records(session, "client", 10000):
                raise RegistrationError("invalid_client_metadata", "Registration capacity reached")
            session.add(
                McpOAuthRecord(
                    key=digest(client_info.client_id),
                    kind="client",
                    payload=data,
                    expires_at=utc_now() + timedelta(days=365),
                )
            )
            await session.commit()

    async def authorize(self, client, params):
        scopes = params.scopes or ["qa"]
        if not params.resource or params.resource != self.resource:
            raise AuthorizeError("invalid_request", "Exact MCP resource required")
        if "qa" not in scopes or not set(scopes) <= {"qa", "qa_operations"}:
            raise AuthorizeError("invalid_scope", "Unsupported scope")
        key = secrets.token_urlsafe(32)
        data = params.model_dump(mode="json")
        data["scopes"] = scopes
        async with self.session() as session:
            if not await self.bound_records(session, "request", 10000):
                raise AuthorizeError("invalid_request", "Authorization capacity reached")
            session.add(
                McpOAuthRecord(
                    key=digest(key),
                    kind="request",
                    expires_at=utc_now() + timedelta(minutes=10),
                    payload={
                        "client_id": client.client_id,
                        "params": data,
                        "client_name": client.client_name or "OAuth MCP",
                    },
                )
            )
            await session.commit()
        return self.origin + "/mcp-authorize?request=" + key

    async def consent_view(self, session, caller, request_id):
        row = await self.record(session, digest(request_id), "request")
        if not row:
            raise HTTPException(409, detail={"message": "授权请求已过期或已处理，请重新连接"})
        if not caller.is_business_user or not await gateway.resolve_caller(session, caller.user_id):
            raise HTTPException(403, detail={"message": "当前账号没有有效业务身份"})
        client = await self.record(session, digest(row.payload["client_id"]), "client")
        if not client:
            raise HTTPException(409, detail={"message": "客户端注册已过期，请重新连接"})
        params = row.payload["params"]
        return {
            "client_name": client.payload.get("client_name") or "未命名应用（名称由应用提供）",
            "redirect_origin": urlsplit(params["redirect_uri"]).netloc,
            "operations_requested": "qa_operations" in (params["scopes"] or ["qa"]),
        }

    async def consent(self, session, caller, request_id, approved, operations, *, trace_id):
        await self.consent_view(session, caller, request_id)
        row = await self.record(session, digest(request_id), "request", lock=True)
        if not row:
            raise HTTPException(409, detail={"message": "授权请求已处理"})
        params = row.payload["params"]
        state = params.get("state")
        if not approved:
            redirect = callback(params["redirect_uri"], error="access_denied", state=state)
        else:
            scopes = params["scopes"] or ["qa"]
            if "qa_operations" in scopes and not operations:
                raise HTTPException(422, detail={"message": "请明确同意操作权限，或拒绝此次授权"})
            code = secrets.token_urlsafe(32)
            data = dict(params)
            data.update(client_id=row.payload["client_id"], user_id=str(caller.user_id))
            data["client_name"] = row.payload["client_name"]
            session.add(
                McpOAuthRecord(
                    key=digest(code),
                    kind="code",
                    payload=data,
                    expires_at=utc_now() + timedelta(minutes=5),
                )
            )
            redirect = callback(params["redirect_uri"], code=code, state=state)
        await session.delete(row)
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action="mcp.oauth.consent",
            trace_id=trace_id,
            target_type="mcp_oauth",
            extra={"approved": approved, "operations": operations if approved else False},
        )
        await session.commit()
        return {"redirect_url": redirect}

    async def load_authorization_code(self, client, authorization_code):
        async with self.session() as session:
            row = await self.record(session, digest(authorization_code), "code")
            if not row or row.payload["client_id"] != client.client_id:
                return None
            return AuthorizationCode(
                code=authorization_code,
                expires_at=aware(row.expires_at).timestamp(),
                **{
                    k: v
                    for k, v in row.payload.items()
                    if k not in {"user_id", "state", "client_name"}
                },
            )

    async def issue(self, session, grant):
        data = dict(grant.payload)
        caller = await gateway.resolve_caller(session, uuid.UUID(data["user_id"]))
        if not caller:
            raise TokenError("invalid_grant", "User no longer eligible")
        rule = await session.get(AgentWhitelistRule, uuid.UUID(data["rule_id"]))
        if not rule or not rule.enabled:
            raise TokenError("invalid_grant", "Grant revoked")
        access, refresh = agent_registry.generate_token(), secrets.token_urlsafe(32)
        rule.token_hash = digest(access)
        rule.token_rotated_at = utc_now()
        rule.token_expires_at = min(utc_now() + timedelta(hours=1), aware(grant.expires_at))
        data["refresh_hash"] = digest(refresh)
        grant.payload = data
        session.add(
            McpOAuthRecord(
                key=digest(refresh),
                kind="refresh",
                expires_at=grant.expires_at,
                payload={
                    "grant": grant.key,
                    "client_id": data["client_id"],
                    "scopes": data["scopes"],
                },
            )
        )
        await session.commit()
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=max(
                1, min(3600, int((aware(rule.token_expires_at) - utc_now()).total_seconds()))
            ),
            refresh_token=refresh,
            scope=" ".join(data["scopes"]),
        )

    async def exchange_authorization_code(self, client, authorization_code):
        async with self.session() as session:
            row = await self.record(session, digest(authorization_code.code), "code", lock=True)
            if not row or row.payload["client_id"] != client.client_id:
                raise TokenError("invalid_grant", "Code already used or expired")
            data = row.payload
            user_id = uuid.UUID(data["user_id"])
            if not await gateway.resolve_caller(session, user_id):
                raise TokenError("invalid_grant", "User no longer eligible")
            rule = AgentWhitelistRule(
                id=uuid.uuid4(),
                provider="workbuddy",
                bound_user_id=user_id,
                agent_identifier="mcp:oauth:" + str(uuid.uuid4()),
                agent_name=data.get("client_name", "OAuth MCP"),
                capability="qa_operations" if "qa_operations" in data["scopes"] else "qa",
                token_hash=digest(secrets.token_urlsafe(32)),
                enabled=True,
                is_self_service=True,
                is_mcp_oauth_grant=True,
                workbuddy_connection_mode="remote",
            )
            session.add(rule)
            grant = McpOAuthRecord(
                key=str(uuid.uuid4()),
                kind="grant",
                expires_at=utc_now() + timedelta(days=30),
                payload={
                    "rule_id": str(rule.id),
                    "user_id": str(user_id),
                    "client_id": client.client_id,
                    "scopes": data["scopes"],
                },
            )
            session.add(grant)
            await session.delete(row)
            await session.flush()
            return await self.issue(session, grant)

    async def load_refresh_token(self, client, refresh_token):
        async with self.session() as session:
            row = await self.record(session, digest(refresh_token), "refresh")
            if not row or row.payload["client_id"] != client.client_id:
                return None
            return RefreshToken(
                token=refresh_token,
                client_id=client.client_id,
                scopes=row.payload["scopes"],
                expires_at=int(aware(row.expires_at).timestamp()),
            )

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        async with self.session() as session:
            row = await self.record(session, digest(refresh_token.token), "refresh")
            grant = (
                await self.record(session, row.payload["grant"], "grant", lock=True)
                if row
                else None
            )
            if not grant or grant.payload["client_id"] != client.client_id:
                raise TokenError("invalid_grant", "Grant not available")
            if grant.payload.get("refresh_hash") != digest(refresh_token.token):
                rule = await session.get(AgentWhitelistRule, uuid.UUID(grant.payload["rule_id"]))
                if rule:
                    rule.enabled = False
                await session.commit()
                raise TokenError("invalid_grant", "Refresh replay: grant revoked")
            if set(scopes) != set(grant.payload["scopes"]):
                raise TokenError("invalid_scope", "Scope change requires new consent")
            return await self.issue(session, grant)

    async def load_access_token(self, token):
        from app.services.mcp_auth import _KapTokenVerifier

        result = await _KapTokenVerifier(self.app).verify_token(token)
        if result:
            result.resource = self.resource
            async with self.session() as session:
                rule = await agent_registry.lookup_enabled_rule(session, token)
                if rule and rule.is_mcp_oauth_grant:
                    grant = await session.scalar(
                        select(McpOAuthRecord).where(
                            McpOAuthRecord.kind == "grant",
                            McpOAuthRecord.payload["rule_id"].as_string() == str(rule.id),
                        )
                    )
                    if not grant or aware(grant.expires_at) <= utc_now():
                        return None
                    result.client_id = grant.payload["client_id"]
                    result.scopes = grant.payload["scopes"]
        return result

    async def revoke_token(self, token):
        async with self.session() as session:
            if isinstance(token, RefreshToken):
                row = await self.record(session, digest(token.token), "refresh")
                grant = (
                    await self.record(session, row.payload["grant"], "grant", lock=True)
                    if row
                    else None
                )
                rule = (
                    await session.get(AgentWhitelistRule, uuid.UUID(grant.payload["rule_id"]))
                    if grant
                    else None
                )
            else:
                rule = await agent_registry.lookup_enabled_rule(session, token.token)
            if rule and rule.is_mcp_oauth_grant:
                rule.enabled = False
                await session.commit()

    async def list_grants(self, session, caller):
        rows = (
            await session.scalars(
                select(McpOAuthRecord)
                .where(
                    McpOAuthRecord.kind == "grant",
                    McpOAuthRecord.expires_at > utc_now(),
                    McpOAuthRecord.payload["user_id"].as_string() == str(caller.user_id),
                )
                .order_by(McpOAuthRecord.expires_at.desc())
                .limit(100)
            )
        ).all()
        items = []
        for row in rows:
            rule = await session.get(AgentWhitelistRule, uuid.UUID(row.payload["rule_id"]))
            if rule and rule.enabled:
                items.append(
                    {
                        "id": row.key,
                        "name": rule.agent_name,
                        "operations_enabled": rule.capability == "qa_operations",
                        "expires_at": aware(row.expires_at),
                    }
                )
        return {"items": items}

    async def revoke_owned_grant(self, session, caller, grant_id, trace_id):
        row = await self.record(session, grant_id, "grant", lock=True)
        if not row or row.payload["user_id"] != str(caller.user_id):
            raise HTTPException(404, detail={"message": "授权不存在或不可管理"})
        rule = await session.get(AgentWhitelistRule, uuid.UUID(row.payload["rule_id"]))
        if rule:
            rule.enabled = False
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action="mcp.oauth.revoked",
            trace_id=trace_id,
            target_type="mcp_oauth",
            target_id=uuid.UUID(row.key),
        )
        await session.commit()
        return {"revoked": True}

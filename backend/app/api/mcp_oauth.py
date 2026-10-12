"""Authenticated consent and user-owned OAuth grant management."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from mcp.server.auth.middleware.client_auth import AuthenticationError, ClientAuthenticator
from pydantic import BaseModel

from app.api.deps import get_caller_context
from app.db.session import get_db


def no_cache(response: Response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


router = APIRouter(
    prefix="/api/v1/auth/mcp-oauth", tags=["MCP OAuth"], dependencies=[Depends(no_cache)]
)
protocol_router = APIRouter()


@protocol_router.post("/revoke", include_in_schema=False)
async def protocol_revoke(request: Request):
    oauth = provider(request)
    try:
        client = await ClientAuthenticator(oauth).authenticate_request(request)
    except AuthenticationError:
        return JSONResponse(
            {"error": "invalid_client"}, status_code=401, headers={"Cache-Control": "no-store"}
        )
    form = await request.form()
    value = form.get("token")
    if not isinstance(value, str) or not value:
        return JSONResponse(
            {"error": "invalid_request"}, status_code=400, headers={"Cache-Control": "no-store"}
        )
    # SDK's revocation request model requires client_secret even for public
    # clients. Keep SDK client authentication, but accept standards-valid
    # public-client requests without a secret. Unknown tokens return success.
    token = await oauth.load_refresh_token(client, value)
    if token is None:
        token = await oauth.load_access_token(value)
    if token is not None and token.client_id == client.client_id:
        await oauth.revoke_token(token)
    return Response(status_code=200, headers={"Cache-Control": "no-store"})


def provider(request):
    value = getattr(request.app.state, "mcp_oauth_provider", None)
    if value is None:
        raise HTTPException(503, detail={"message": "OAuth 接入尚未启用，请使用现有凭证接入"})
    return value


class ConsentCommand(BaseModel):
    approved: bool
    operations: bool = False


@router.get("/requests/{request_id}")
async def consent_view(
    request: Request,
    request_id: str,
    caller=Depends(get_caller_context),
    session=Depends(get_db),
):
    return await provider(request).consent_view(session, caller, request_id)


@router.post("/requests/{request_id}")
async def consent(
    request: Request,
    request_id: str,
    command: ConsentCommand,
    caller=Depends(get_caller_context),
    session=Depends(get_db),
):
    return await provider(request).consent(
        session,
        caller,
        request_id,
        command.approved,
        command.operations,
        trace_id=request.state.trace_id,
    )


@router.get("/grants")
async def grants(
    request: Request,
    caller=Depends(get_caller_context),
    session=Depends(get_db),
):
    return await provider(request).list_grants(session, caller)


@router.delete("/grants/{grant_id}")
async def revoke(
    request: Request,
    grant_id: str,
    caller=Depends(get_caller_context),
    session=Depends(get_db),
):
    return await provider(request).revoke_owned_grant(
        session, caller, grant_id, request.state.trace_id
    )

"""Serve the candidate SPA and real KAP API together, only in the isolated UI container."""

from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles


class SpaFiles(StaticFiles):
    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or scope["method"] not in {"GET", "HEAD"}:
                raise
            # Never mask missing assets or backend routes with an HTML success.
            if Path(path).suffix or path.replace("\\", "/").startswith(
                ("api/", "admin/ops", "mcp")
            ):
                raise
            return FileResponse(Path(self.directory) / "index.html")


def create_app():
    from app.main import app as backend

    files = Starlette(routes=[Mount("/", SpaFiles(directory="/evidence/ui-dist", html=True))])

    async def combined(scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or path.startswith(
            ("/api/", "/admin/ops", "/health", "/mcp", "/.well-known/")
        ):
            await backend(scope, receive, send)
        else:
            await files(scope, receive, send)

    return combined

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import Settings, get_settings

_bearer_scheme = HTTPBearer(auto_error=True)


def require_bearer_token(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> None:
    if not secrets.compare_digest(credentials.credentials, settings.auth_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing bearer token",
        )


class BearerTokenMiddleware:
    """The same static token as require_bearer_token, for a mounted ASGI app.

    FastAPI's dependency never runs for a `Mount`ed sub-application, so the
    MCP endpoint needs its own check. Kept in this module so there is one
    place that compares against `settings.auth_token`.
    """

    def __init__(self, app: ASGIApp, token: str) -> None:
        self._app = app
        self._token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        header = Headers(scope=scope).get("authorization", "")
        scheme, _, credentials = header.partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(credentials, self._token):
            response = JSONResponse(
                {"detail": "Invalid or missing bearer token"},
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return

        await self._app(scope, receive, send)

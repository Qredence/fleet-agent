"""Hardening middleware: request ids, optional API-key auth, body-size cap."""

import contextvars
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.settings import Settings

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)

_PUBLIC_PATHS = {"/health", "/ready"}


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        token = request_id_ctx.set(request_id)
        try:
            response: Response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        response.headers["X-Request-Id"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Optional API-key auth + request size limit (plan.md Phase 12).

    Auth is only enforced when settings.api_key is configured — dev runs
    without a key stay open (advisory logged at startup).
    """

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        settings = self._settings

        if request.url.path not in _PUBLIC_PATHS:
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > settings.max_body_bytes:
                return JSONResponse(
                    status_code=413,
                    content={"detail": "Request body too large."},
                )

            if (
                settings.api_key is not None
                and request.url.path.startswith("/api/")
                and request.method != "OPTIONS"
            ):
                provided = request.headers.get("x-api-key")
                if provided is None or provided != settings.api_key.get_secret_value():
                    return JSONResponse(
                        status_code=401, content={"detail": "Unauthorized."}
                    )
        return await call_next(request)

"""Hardening middleware: request ids, optional API-key auth, body-size cap."""

import contextvars
import secrets
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

# Every path NOT listed here requires the API key when one is configured.
# This is an explicit allowlist so a new un-prefixed route (e.g. /metrics) cannot
# silently ship unauthenticated; the previous `/api/`-prefix test did exactly that.
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


class RequestGuardMiddleware(BaseHTTPMiddleware):
    """Optional API-key auth + request size limit.

    Auth is only enforced when ``settings.api_key`` is configured — dev runs
    without a key stay open (advisory logged at startup). Every path outside
    ``_PUBLIC_PATHS`` is protected, including un-prefixed routes such as
    ``/metrics`` and the OpenAPI docs.

    The name is deliberate: this middleware does NOT set security headers.
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
            if content_length:
                try:
                    length = int(content_length)
                except ValueError:
                    return JSONResponse(
                        status_code=400,
                        content={"detail": "Invalid Content-Length header."},
                    )
                if length > settings.max_body_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "Request body too large."},
                    )

            if settings.api_key is not None and request.method != "OPTIONS":
                provided = request.headers.get("x-api-key")
                if provided is None or not secrets.compare_digest(
                    provided, settings.api_key.get_secret_value()
                ):
                    return JSONResponse(
                        status_code=401, content={"detail": "Unauthorized."}
                    )
        return await call_next(request)

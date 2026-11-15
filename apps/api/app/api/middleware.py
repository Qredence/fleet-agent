"""Hardening middleware: request ids, optional API-key auth, body-size cap."""

import contextvars
import secrets
import uuid

from fastapi.responses import JSONResponse
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.settings import Settings

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)

# Every path NOT listed here requires the API key when one is configured.
# This is an explicit allowlist so a new un-prefixed route (e.g. /metrics) cannot
# silently ship unauthenticated; the previous `/api/`-prefix test did exactly that.
_PUBLIC_PATHS = {"/health", "/ready"}


class _BodyTooLargeError(BaseException):
    """Internal sentinel raised by guarded ASGI receive on oversized bodies.

    Inherits from ``BaseException`` rather than ``Exception`` so Starlette's
    inner ``ServerErrorMiddleware`` does not intercept it and emit a 500
    response before ``RequestGuardMiddleware`` sends 413.
    """


async def _send_json_error(
    scope: Scope,
    receive: Receive,
    send: Send,
    status_code: int,
    detail: str,
) -> None:
    response = JSONResponse(status_code=status_code, content={"detail": detail})
    await response(scope, receive, send)


class RequestIdMiddleware:
    """Pure ASGI middleware attaching a per-request correlation id."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex[:16]
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_ctx.set(request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-Id"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            request_id_ctx.reset(token)


class RequestGuardMiddleware:
    """Pure ASGI middleware enforcing optional API-key auth and body-size limits.

    Auth is only enforced when ``settings.api_key`` is configured — dev runs
    without a key stay open (advisory logged at startup). Every path outside
    ``_PUBLIC_PATHS`` is protected, including un-prefixed routes such as
    ``/metrics`` and the OpenAPI docs.
    """

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self._settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        app_obj = scope.get("app")
        app_state = getattr(app_obj, "state", None)
        settings = getattr(app_state, "settings", None) or self._settings
        path = scope.get("path", "")
        if path in _PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        content_length = headers.get("content-length")
        if content_length is not None:
            try:
                length = int(content_length)
            except ValueError:
                await _send_json_error(
                    scope, receive, send, 400, "Invalid Content-Length header."
                )
                return
            if length < 0:
                await _send_json_error(
                    scope, receive, send, 400, "Invalid Content-Length header."
                )
                return
            if length > settings.max_body_bytes:
                await _send_json_error(
                    scope, receive, send, 413, "Request body too large."
                )
                return

        if settings.api_key is not None and scope.get("method") != "OPTIONS":
            provided = headers.get("x-api-key")
            if provided is None or not secrets.compare_digest(
                provided, settings.api_key.get_secret_value()
            ):
                await _send_json_error(scope, receive, send, 401, "Unauthorized.")
                return

        received_bytes = 0
        response_started = False
        max_bytes = settings.max_body_bytes

        async def guarded_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > max_bytes:
                    raise _BodyTooLargeError
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, guarded_receive, tracked_send)
        except _BodyTooLargeError:
            if not response_started:
                await _send_json_error(
                    scope, receive, send, 413, "Request body too large."
                )

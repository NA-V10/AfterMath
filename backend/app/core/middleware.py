"""Pure-ASGI middleware: request id, environment marker header, access log with timing."""

from __future__ import annotations

import json
import time
import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import request_id_var
from app.core.logging import get_logger

log = get_logger("aftermath.access")

ENVIRONMENT_HEADER = (b"x-aftermath-environment", b"SIMULATION")
# JSON API: never sniffed, framed, cached by shared caches or given a referrer (docs/SECURITY.md).
SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cache-control", b"no-store"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
]


def _incoming_request_id(scope: Scope) -> str:
    for name, value in scope.get("headers", []):
        if name == b"x-request-id":
            try:
                return str(uuid.UUID(value.decode("latin-1")))
            except ValueError:
                break  # untrusted / malformed: replace
    return str(uuid.uuid4())


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_request_id(scope)
        token = request_id_var.set(request_id)
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                headers.append(ENVIRONMENT_HEADER)
                present = {name.lower(): value for name, value in headers}
                html = present.get(b"content-type", b"").startswith(b"text/html")  # /docs page
                headers.extend(
                    h
                    for h in SECURITY_HEADERS
                    if h[0] not in present and not (html and h[0] == b"content-security-policy")
                )
                message["headers"] = headers
            await send(message)

        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send_wrapper(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            # Last-resort handler: never leak internals; keep the request id on the response.
            log.error("unhandled_error", error_type=type(exc).__name__, exc_info=exc)
            if response_started:
                raise
            body = json.dumps(
                {
                    "type": "https://aftermath.local/problems/internal-error",
                    "title": "Internal error",
                    "status": 500,
                    "detail": (
                        "An unexpected error occurred. Quote the request_id when reporting it."
                    ),
                    "instance": scope.get("path"),
                    "request_id": request_id,
                }
            ).encode()
            await tracking_send(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [(b"content-type", b"application/problem+json")],
                }
            )
            await tracking_send({"type": "http.response.body", "body": body})
        finally:
            log.info(
                "http_request",
                method=scope.get("method"),
                path=scope.get("path"),
                status=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            structlog.contextvars.unbind_contextvars("request_id")
            request_id_var.reset(token)

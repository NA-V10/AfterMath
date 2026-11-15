"""Domain-level errors and RFC 9457 problem+json rendering.

Internal exception details are never returned to clients; they are logged with the request id.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import request_id_var
from app.core.logging import get_logger

PROBLEM_BASE = "https://aftermath.local/problems/"
log = get_logger(__name__)


class AppError(Exception):
    status = 500
    slug = "internal-error"
    title = "Internal error"

    def __init__(self, detail: str, *, extra: dict[str, Any] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extra = extra or {}


class NotFoundError(AppError):
    status, slug, title = 404, "not-found", "Resource not found"


class ConflictError(AppError):
    status, slug, title = 409, "conflict", "Conflict with current state"


class InvalidInputError(AppError):
    status, slug, title = 422, "invalid-input", "Invalid input"


class ServiceUnavailableError(AppError):
    status, slug, title = 503, "service-unavailable", "Dependency unavailable"


def problem(
    request: Request,
    status: int,
    slug: str,
    title: str,
    detail: str,
    **extra: Any,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": PROBLEM_BASE + slug,
        "title": title,
        "status": status,
        "detail": detail,
        "instance": request.url.path,
        "request_id": request_id_var.get(),
        **extra,
    }
    return JSONResponse(body, status_code=status, media_type="application/problem+json")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return problem(request, exc.status, exc.slug, exc.title, exc.detail, **exc.extra)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return problem(
            request,
            422,
            "validation-error",
            "Request validation failed",
            "One or more request parameters are invalid.",
            errors=errors,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        slug = {404: "not-found", 405: "method-not-allowed"}.get(exc.status_code, "http-error")
        return problem(request, exc.status_code, slug, str(exc.detail), str(exc.detail))

    @app.exception_handler(OperationalError)
    @app.exception_handler(DBAPIError)
    async def _db(request: Request, exc: Exception) -> JSONResponse:
        log.error("database_error", error_type=type(exc).__name__, exc_info=exc)
        return problem(
            request,
            503,
            "database-unavailable",
            "Database unavailable",
            "The database could not be reached. Try again shortly.",
        )

    @app.exception_handler(ConnectionError)
    @app.exception_handler(TimeoutError)
    async def _dependency_down(request: Request, exc: Exception) -> JSONResponse:
        # asyncpg raises raw OSErrors (e.g. ConnectionRefusedError) on connect, which
        # SQLAlchemy does not wrap. Phase 1 has no other outbound connections.
        log.error("dependency_unavailable", error_type=type(exc).__name__)
        return problem(
            request,
            503,
            "dependency-unavailable",
            "Dependency unavailable",
            "A required backing service (database) could not be reached. Try again shortly.",
        )

    # Any other exception is handled by RequestContextMiddleware (generic 500 problem).

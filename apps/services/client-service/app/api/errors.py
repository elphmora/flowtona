"""
app/api/errors.py

Translates every exception this API can raise into a consistent RFC
9457 Problem Details response (Platform Conventions §6). Matches
identity-service's app/api/errors.py closely — three handlers here,
not four: no equivalent of identity-service's IdentityInvariantError
exists yet, since nothing in client-service currently raises anything
in that category. A deliberate simplification, not an oversight — add
that handler if/when a genuine internal-consistency-bug case shows up
that needs distinguishing from a plain unhandled exception.
"""

import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.config import settings
from app.exceptions.base import DomainError

logger = logging.getLogger(__name__)


class ValidationErrorDetail(BaseModel):
    field: str
    message: str


class ProblemDetail(BaseModel):
    type: str
    title: str
    status: int
    detail: str
    instance: str
    code: str
    request_id: str
    errors: list[ValidationErrorDetail] | None = None


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or str(uuid4())


def _type_uri(code: str) -> str:
    return f"{settings.ERROR_BASE_URI}/{code.replace('_', '-')}"


_REQUEST_LOCATION_PREFIXES = {"body", "query", "path", "header", "cookie"}


def _format_validation_errors(
    exc: RequestValidationError,
) -> list[ValidationErrorDetail]:
    formatted = []
    for error in exc.errors():
        loc = error.get("loc", ())
        if loc and loc[0] in _REQUEST_LOCATION_PREFIXES:
            field_parts = loc[1:]
        else:
            field_parts = loc
        field = ".".join(str(part) for part in field_parts) if field_parts else "body"
        formatted.append(
            ValidationErrorDetail(
                field=field, message=error.get("msg", "Invalid value")
            )
        )
    return formatted


def _problem_response(
    *,
    request: Request,
    code: str,
    title: str,
    status_code: int,
    detail: str,
    errors: list[ValidationErrorDetail] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    problem = ProblemDetail(
        type=_type_uri(code),
        title=title,
        status=status_code,
        detail=detail,
        instance=request.url.path,
        code=code,
        request_id=_request_id(request),
        errors=errors,
    )
    return JSONResponse(
        status_code=status_code,
        content=problem.model_dump(exclude_none=True),
        media_type="application/problem+json",
        headers=headers,
    )


async def handle_domain_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    # WWW-Authenticate: Bearer on every 401, per RFC 7235/6750 — not
    # specific to InvalidAccessTokenError by name, so any future
    # DomainError that happens to be a 401 gets the correct challenge
    # header automatically, without needing its own special case here.
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return _problem_response(
        request=request,
        code=exc.code,
        title=exc.title,
        status_code=exc.status_code,
        detail=exc.detail,
        headers=headers,
    )


async def handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return _problem_response(
        request=request,
        code="validation_failed",
        title="Validation failed",
        status_code=422,
        detail="The request body or query parameters failed validation.",
        errors=_format_validation_errors(exc),
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception")
    return _problem_response(
        request=request,
        code="internal_server_error",
        title="Internal Server Error",
        status_code=500,
        detail="An internal server error occurred.",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, handle_domain_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(Exception, handle_unexpected_error)

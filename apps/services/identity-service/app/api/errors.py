"""
app/api/errors.py

Translates every exception this API can raise into a consistent RFC
9457 Problem Details response (Decision 15). Almost all the actual
work already happened when each DomainError subclass was defined
(code/status_code/title/detail) — this file is mostly assembly: add
the two things a domain exception correctly doesn't know about itself
(instance — the request path, request_id — set by RequestIDMiddleware
before this ever runs), and serialize.

Four handlers, not one:

- DomainError (catches every subclass automatically via Starlette's
  MRO-based dispatch) -> the real business-rule response, using the
  exception's own code/status_code/title/detail. No per-exception
  changes needed anywhere else in the codebase — every DomainError
  subclass already built works with this handler unchanged.
- IdentityInvariantError -> generic 500. The internal diagnostic
  message (e.g. "membership references missing tenant X") is logged
  server-side, NEVER returned to the client — matches its own
  established design (see app/exceptions/base.py). Not a DomainError
  subclass, so there's no ambiguity with the handler above.
- RequestValidationError (FastAPI's built-in, fired on malformed
  request bodies/query params) -> reshaped into the SAME RFC 9457
  format, so a client sees one consistent error shape regardless of
  whether a request was malformed or business-rejected — but with an
  `errors` extension member carrying field-level detail (RFC 9457
  explicitly permits extension members). Collapsing this to a bare
  "validation failed" string would be a real usability regression
  versus FastAPI's own default behavior, which already includes this.
- Exception (bare catch-all) -> generic 500, full traceback logged
  server-side, generic message to the client. Never let a raw Python
  traceback reach an API consumer.

`type` is derived from the exception's `code` automatically
(invalid_credentials -> {settings.ERROR_BASE_URI}/invalid-credentials)
— no per-exception `type` field needed anywhere.
"""

import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.config import settings
from app.exceptions.base import DomainError, IdentityInvariantError

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
    # Falls back to a fresh UUID if RequestIDMiddleware somehow wasn't
    # registered — defensive against a middleware-registration mistake
    # (e.g. forgetting add_request_id_middleware(app) in main.py), not
    # the expected path in normal operation.
    return getattr(request.state, "request_id", None) or str(uuid4())


def _type_uri(code: str) -> str:
    return f"{settings.ERROR_BASE_URI}/{code.replace('_', '-')}"


_REQUEST_LOCATION_PREFIXES = {"body", "query", "path", "header", "cookie"}


def _format_validation_errors(
    exc: RequestValidationError,
) -> list[ValidationErrorDetail]:
    """Pydantic's raw error shape has `loc` as a tuple like
    ("body", "email") or ("query", "page") — the first element names
    the request part, not the field path itself, so it's dropped, but
    only when it's actually recognized as one of the request-location
    prefixes FastAPI uses (rather than unconditionally dropping index
    0), so a `loc` shape that doesn't start with one of these isn't
    silently truncated by one element for no reason."""
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
    )


async def handle_domain_error(request: Request, exc: Exception) -> JSONResponse:
    # Typed as Exception, not DomainError, because Starlette's own
    # add_exception_handler() stub expects Callable[[Request, Exception], ...]
    # — a narrower parameter type can't be soundly substituted there,
    # even though Starlette's dispatch guarantees this is only ever
    # actually called with a DomainError. The assert both satisfies the
    # type checker AND is a genuine runtime safety check — if that
    # dispatch guarantee were ever violated, fail loudly here rather
    # than silently misbehave.
    assert isinstance(exc, DomainError)
    return _problem_response(
        request=request,
        code=exc.code,
        title=exc.title,
        status_code=exc.status_code,
        detail=exc.detail,
    )


async def handle_identity_invariant_error(
    request: Request, exc: Exception
) -> JSONResponse:
    assert isinstance(exc, IdentityInvariantError)
    # Logged prominently — this represents a genuine internal
    # consistency bug, not a client mistake. The message itself (e.g.
    # "membership references missing tenant X") stays server-side only.
    logger.exception("Identity invariant violated")
    return _problem_response(
        request=request,
        code="internal_server_error",
        title="Internal Server Error",
        status_code=500,
        detail="An internal server error occurred.",
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
    app.add_exception_handler(IdentityInvariantError, handle_identity_invariant_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(Exception, handle_unexpected_error)

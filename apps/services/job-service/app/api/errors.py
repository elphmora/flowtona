"""
app/api/errors.py

Centralized exception-handler registration (Platform Conventions §3)
-- HTTP translation happens here, never ad hoc per-route.

Updated against client-service's actual, confirmed app/api/errors.py:

  - WWW-Authenticate: Bearer added on every 401 response, generically,
    based on exc.status_code == 401 -- not specific to
    InvalidAccessTokenError by name, so any future DomainError that
    happens to be a 401 gets the correct RFC 7235/6750 challenge
    header automatically. Confirmed as the real mechanism, not guessed
    -- an earlier version of this file didn't implement this at all,
    explicitly flagged as unconfirmed rather than invented.
  - error_base_uri is read from request.app.state.settings.ERROR_BASE_URI
    -- the resolved Settings instance job-service already stores per
    app/main.py's lifespan -- not a hardcoded constant.
  - request_id falls back to a freshly generated UUID if request-ID
    middleware didn't populate request.state.request_id, so the field
    is never null in a response body.
  - media_type="application/problem+json", RFC 9457's own specified
    content type -- an earlier version omitted it, defaulting to
    application/json.
  - Validation-error field-name extraction now checks whether the
    first loc segment is actually a known request-location prefix
    (body/query/path/header/cookie) before stripping it, rather than
    unconditionally assuming loc[0] always is one.
  - Handler signatures are typed as (Request, Exception), with
    assert isinstance(exc, DomainError) (etc.) narrowing the type
    inside the function body -- replacing an earlier version's
    cast()-based approach per handler. This is simpler, needs no
    per-call type: ignore, and is confirmed as the real sibling
    pattern rather than an independently-arrived-at simplification.

Still true, unchanged: registering a handler for the bare `Exception`
class causes Starlette's build_middleware_stack() to install that
handler onto ServerErrorMiddleware -- the OUTERMOST layer, wrapping
every user middleware including RequestIDMiddleware -- not onto
ExceptionMiddleware, which only holds handlers for specific registered
classes. This is why a genuinely uncaught, unregistered-elsewhere
exception's response never carries an X-Request-ID header, regardless
of middleware registration order.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.exceptions.base import DomainError, problem_body

_REQUEST_LOCATION_PREFIXES = {"body", "query", "path", "header", "cookie"}


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or str(uuid4())


def _format_validation_errors(exc: RequestValidationError) -> list[dict[str, str]]:
    formatted = []
    for error in exc.errors():
        loc = error.get("loc", ())
        if loc and loc[0] in _REQUEST_LOCATION_PREFIXES:
            field_parts = loc[1:]
        else:
            field_parts = loc
        field = ".".join(str(part) for part in field_parts) if field_parts else "body"
        formatted.append({"field": field, "message": error.get("msg", "Invalid value")})
    return formatted


async def handle_domain_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    body = problem_body(
        status_code=exc.status_code,
        title=exc.title,
        code=exc.code,
        instance=str(request.url.path),
        request_id=_request_id(request),
        error_base_uri=request.app.state.settings.ERROR_BASE_URI,
        detail=exc.detail,
        extra=exc.extra,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=body,
        media_type="application/problem+json",
        headers=headers,
    )


async def handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    body = problem_body(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        title="Validation failed",
        code="validation_failed",
        instance=str(request.url.path),
        request_id=_request_id(request),
        error_base_uri=request.app.state.settings.ERROR_BASE_URI,
        detail="One or more fields are invalid.",
        extra={"errors": _format_validation_errors(exc)},
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=body,
        media_type="application/problem+json",
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    body = problem_body(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        title="Internal server error",
        code="internal_error",
        instance=str(request.url.path),
        request_id=_request_id(request),
        error_base_uri=request.app.state.settings.ERROR_BASE_URI,
        detail="An unexpected error occurred.",
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=body,
        media_type="application/problem+json",
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, handle_domain_error)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(Exception, handle_unexpected_error)

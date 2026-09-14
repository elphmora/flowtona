"""
app/api/errors.py

Centralized exception-handler registration (Platform Conventions §3)
-- HTTP translation happens here, never ad hoc per-route.

Every handler's own signature accepts `Exception`, matching Starlette's
add_exception_handler stub exactly, rather than the narrower real type
each handler actually only ever receives at runtime (DomainError,
RequestValidationError). The narrower type is recovered with a single
cast() at the top of each handler body instead. An earlier version
tried to resolve this mismatch with inline `# type: ignore[arg-type]`
comments at the registration call sites -- that approach turned out to
be fragile in practice: ruff format's line-wrapping moved those
comments onto lines mypy could no longer associate with the actual
call, producing "Invalid type: ignore comment" syntax errors on the
next run. cast() is an ordinary expression, immune to reformatting,
and doesn't depend on a magic comment sitting on one exact physical
line.

Corrected explanation of a real, accepted limitation: registering a
handler for the bare `Exception` class causes Starlette's
`build_middleware_stack()` to install that handler onto
`ServerErrorMiddleware` -- the OUTERMOST layer, wrapping every user
middleware including RequestIDMiddleware -- not onto
`ExceptionMiddleware`, which only holds handlers for specific
registered classes (DomainError, RequestValidationError, both handled
below). This is why a genuinely uncaught, unregistered-elsewhere
exception's response never carries an X-Request-ID header: it's built
by a layer that sits outside RequestIDMiddleware's reach entirely,
regardless of middleware registration order. Every DomainError and
RequestValidationError response, by contrast, is built by handlers
Starlette does install inside ExceptionMiddleware, which IS wrapped by
RequestIDMiddleware -- those responses reliably carry the header.
"""

from __future__ import annotations

from typing import cast

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.exceptions.base import DomainError, problem_body


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


async def _handle_domain_error(request: Request, exc: Exception) -> JSONResponse:
    # Starlette only ever invokes this handler for DomainError (or a
    # subclass) -- it was registered against that class specifically,
    # below. The cast recovers that narrower type for the body of this
    # function; the signature above stays Exception to match Starlette's
    # own stub exactly, so no mismatch exists at the registration site.
    domain_exc = cast(DomainError, exc)
    body = problem_body(
        status_code=domain_exc.status_code,
        title=domain_exc.title,
        code=domain_exc.code,
        instance=str(request.url.path),
        request_id=_request_id(request),
        detail=domain_exc.detail,
        extra=domain_exc.extra,
    )
    return JSONResponse(status_code=domain_exc.status_code, content=body)


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    validation_exc = cast(RequestValidationError, exc)
    errors = [
        {"field": ".".join(str(p) for p in err["loc"][1:]), "message": err["msg"]}
        for err in validation_exc.errors()
    ]
    body = problem_body(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        title="Validation failed",
        code="validation_failed",
        instance=str(request.url.path),
        request_id=_request_id(request),
        detail="One or more fields are invalid.",
        extra={"errors": errors},
    )
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content=body)


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    body = problem_body(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        title="Internal server error",
        code="internal_error",
        instance=str(request.url.path),
        request_id=_request_id(request),
        detail="An unexpected error occurred.",
    )
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=body)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _handle_domain_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)

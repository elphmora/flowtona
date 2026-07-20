"""
app/middleware/request_id.py

Assigns a request_id to every incoming request, before anything else
runs — the exception handler (app/api/errors.py) depends on
request.state.request_id already being set by the time it fires.

Honors an incoming X-Request-ID header if the client (or an upstream
gateway, e.g. Kong) already supplied one, so a request can be traced
consistently across service boundaries rather than getting a new,
disconnected ID at each hop. Generates a fresh UUID otherwise.

Also sets X-Request-ID on the OUTGOING response, on both success and
failure — lets a specific response be correlated back to server-side
logs without needing the response body's request_id field, which only
exists on error responses in the first place.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        try:
            response = await call_next(request)
        except Exception:
            # Should not happen in practice — the registered catch-all
            # Exception handler (app/api/errors.py) converts any raised
            # exception into a proper Response before it reaches this
            # point. If this ever fires anyway, that assumption broke
            # somewhere, which is worth surfacing explicitly rather than
            # silently losing the X-Request-ID header on the way out.
            logger.exception(
                "Request failed before exception handlers could produce "
                "a response (request_id=%s)",
                request_id,
            )
            raise

        response.headers["X-Request-ID"] = request_id
        return response


def add_request_id_middleware(app: FastAPI) -> None:
    app.add_middleware(RequestIDMiddleware)

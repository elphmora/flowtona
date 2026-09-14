"""
app/middleware/request_id.py

Pure ASGI middleware, not Starlette's BaseHTTPMiddleware —
BaseHTTPMiddleware runs downstream code in a separate task internally,
which Starlette itself documents as disrupting ContextVar propagation
between the middleware and downstream code.

Registered via add_request_id_middleware(app), called first in
app/main.py's middleware setup — meaning it's the INNERMOST of the
custom middlewares (closest to the router), so it wraps every route
handler and every registered DomainError/RequestValidationError
handler. It does NOT wrap responses built entirely by Starlette's own
ServerErrorMiddleware (a genuinely uncaught, unregistered exception) —
see app/api/errors.py's docstring for the corrected explanation of
exactly why.
"""

from __future__ import annotations

import uuid
from collections.abc import MutableMapping
from typing import Any

from fastapi import FastAPI
from starlette.types import ASGIApp, Receive, Scope, Send

REQUEST_ID_HEADER = b"x-request-id"
MAX_INCOMING_REQUEST_ID_LENGTH = 128


class RequestIDMiddleware:
    """Ensures every HTTP request has a request ID, available via
    `request.state.request_id` and echoed back as `X-Request-ID`.
    Honors a caller-supplied ID (within a sane length) rather than
    always generating a fresh one."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = next(
            (v for k, v in scope.get("headers", []) if k == REQUEST_ID_HEADER),
            None,
        )
        if incoming and 0 < len(incoming) <= MAX_INCOMING_REQUEST_ID_LENGTH:
            request_id = incoming.decode("latin-1")
        else:
            request_id = str(uuid.uuid4())

        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id

        async def send_with_request_id(message: MutableMapping[str, Any]) -> None:
            # Typed as MutableMapping[str, Any], not bare dict, to match
            # Starlette's Send protocol exactly (Callable[[MutableMapping
            # [str, Any]], Awaitable[None]]) -- mypy rejects a narrower
            # dict[Any, Any] parameter type here under contravariant
            # Callable matching, even though every real ASGI message is
            # in fact a plain dict at runtime.
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append((REQUEST_ID_HEADER, request_id.encode("latin-1")))
            await send(message)

        await self.app(scope, receive, send_with_request_id)


def add_request_id_middleware(app: FastAPI) -> None:
    app.add_middleware(RequestIDMiddleware)

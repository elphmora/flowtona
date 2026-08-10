"""
app/middleware/request_id.py

Assigns a request_id to every incoming request, written into
scope.setdefault("state", {})["request_id"] — which is what
request.state actually reads/writes under the hood in Starlette — so
app/api/errors.py's existing _request_id() helper keeps working
unmodified. Echoed back as the X-Request-ID response header.

Honors a valid inbound X-Request-ID header when present, generating a
fresh one otherwise. Rejects malformed/oversized inbound values rather
than trusting them verbatim, since this value ends up in structured
logs as operational data.

Does not guarantee the header is present on every possible response —
specifically, a response built by Starlette's own generic error
handling (rather than by one of this app's own registered exception
handlers) is constructed outside this middleware's reach. See
client-service-architecture.md's Entity & Convention Clarifications
for the full reasoning and the Starlette internals this is derived
from.
"""

from uuid import uuid4

from fastapi import FastAPI
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_REQUEST_ID_HEADER_BYTES = b"x-request-id"
_REQUEST_ID_HEADER_STR = "X-Request-ID"
_REQUEST_ID_MAX_LENGTH = 128
_REQUEST_ID_ALLOWED_EXTRA_CHARS = frozenset("-_.")


def _extract_request_id(scope: Scope) -> str | None:
    """Reads and validates X-Request-ID from raw ASGI headers (a list
    of (bytes, bytes) tuples). Returns None if absent or invalid.

    Deliberately strict (alphanumeric plus -_. only) — Flowtona owns
    request IDs completely for now; this does not attempt to accept
    other formats (e.g. W3C Trace Context). Revisit if upstream trace
    propagation becomes a real need, not preemptively."""
    for raw_name, raw_value in scope.get("headers", []):
        if raw_name.lower() == _REQUEST_ID_HEADER_BYTES:
            try:
                value = raw_value.decode("latin-1").strip()
            except UnicodeDecodeError:
                return None
            if not value or len(value) > _REQUEST_ID_MAX_LENGTH:
                return None
            if not all(
                char.isalnum() or char in _REQUEST_ID_ALLOWED_EXTRA_CHARS
                for char in value
            ):
                return None
            return value
    return None


class RequestIDMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _extract_request_id(scope) or str(uuid4())
        state = scope.setdefault("state", {})
        state["request_id"] = request_id

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers[_REQUEST_ID_HEADER_STR] = request_id
            await send(message)

        await self.app(scope, receive, send_wrapper)


def add_request_id_middleware(app: FastAPI) -> None:
    app.add_middleware(RequestIDMiddleware)

"""
app/exceptions/base.py

RFC 9457 Problem Details shape, per Platform Conventions §6. Every
error response is {"type", "title", "status", "detail", "instance"}
extended with "code" and "request_id". This module defines what a
domain exception IS (the class hierarchy); app/api/errors.py defines
how one becomes an HTTP response.

`detail` is always present in the body, never conditionally omitted —
falls back to `title` if the caller doesn't supply one. An earlier
draft made this field conditional ("if detail is not None:
body['detail'] = detail"), which meant the documented contract
("every response contains detail") and the actual implementation could
silently disagree. This version keeps the promise, deliberately, over
leaving detail out when a caller forgets to pass one.
"""

from __future__ import annotations

from typing import Any

from fastapi import status

PROBLEM_BASE_URI = "https://flowtona.dev/errors"


class DomainError(Exception):
    """Base for every job-service domain exception (Phase 1 onward).

    Subclasses set these class-level attributes; app/api/errors.py's
    generic handler reads them, so a new domain exception needs no new
    handler registration — only a new subclass.
    """

    status_code: int = status.HTTP_400_BAD_REQUEST
    title: str = "Domain error"
    code: str = "domain_error"

    def __init__(self, detail: str | None = None, **extra: Any) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extra = extra or None


def problem_body(
    *,
    status_code: int,
    title: str,
    code: str,
    instance: str,
    request_id: str | None,
    detail: str | None = None,
    type_suffix: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the RFC 9457 Problem Details body as a plain dict.

    Deliberately takes plain values (no FastAPI/Starlette Request
    dependency) so it can be unit-tested without spinning up an app —
    app/api/errors.py's handlers extract instance/request_id from the
    real Request and pass them in here.
    """
    suffix = type_suffix or code.replace("_", "-")
    body: dict[str, Any] = {
        "type": f"{PROBLEM_BASE_URI}/{suffix}",
        "title": title,
        "status": status_code,
        "detail": detail if detail is not None else title,
        "instance": instance,
        "code": code,
        "request_id": request_id,
    }
    if extra:
        body.update(extra)
    return body

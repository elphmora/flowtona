"""
app/exceptions/base.py

RFC 9457 Problem Details shape, per Platform Conventions §6.

error_base_uri is now an explicit parameter to problem_body(), not a
hardcoded module constant -- an earlier version hardcoded
PROBLEM_BASE_URI, a real divergence from client-service's own
confirmed pattern of sourcing it from Settings.ERROR_BASE_URI, now
fixed. app/api/errors.py sources it from request.app.state.settings.

DomainError is intentionally NOT simplified to match client-service's
own, simpler auth.py exceptions (positional detail, no **extra) --
job-service's own future errors (Complete Job's three-way failure
shape, 03-api-contract.md, which needs an arbitrary outstanding_visits
field beyond detail) genuinely need the **extra mechanism this class
already provides. detail is guaranteed present in the body (falling
back to title) -- a deliberate, already-reviewed fix, kept regardless
of whichever simpler pattern any individual sibling exception happens
to use.
"""

from __future__ import annotations

from typing import Any

from fastapi import status


class DomainError(Exception):
    """Base for every job-service domain exception."""

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
    request_id: str,
    error_base_uri: str,
    detail: str | None = None,
    type_suffix: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the RFC 9457 Problem Details body as a plain dict.

    Deliberately takes plain values (no FastAPI/Starlette Request
    dependency) so it can be unit-tested without spinning up an app --
    app/api/errors.py's handlers extract instance/request_id/
    error_base_uri from the real Request and its app.state and pass
    them in here.
    """
    suffix = type_suffix or code.replace("_", "-")
    body: dict[str, Any] = {
        "type": f"{error_base_uri}/{suffix}",
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

"""
app/exceptions/base.py

Base classes for the two distinct exception categories services use.

DomainError: a genuine, expected business outcome with a stable
machine-readable code and an HTTP status (Decision 8: service raises,
route translates to RFC 9457 per Decision 15/Amendment 1's code field).
code, status_code, and title stay coupled on one class — each
DomainError subclass has exactly one of each in every context it's
raised in, so a side-table mapping exception type -> status/title would
just be one more place for the same fact to drift out of sync. The
route handler still owns the remaining transport-specific pieces
(type URI, instance path, request_id, application/problem+json
serialization) — the separation stays meaningful even with these three
fields living on the exception.

IdentityInvariantError: NOT a DomainError, no RFC 9457 mapping. Raised
when persisted state contradicts something that should be structurally
impossible given currently designed features (e.g. an EmailVerification
record pointing at a user_id that doesn't exist, or referencing an
email that no longer matches the user's current one). A bug signal —
logged prominently, returned externally only as a generic internal
error — not a normal user-facing outcome, deliberately a plain
RuntimeError subclass, not routed through the domain-exception
machinery.
"""


class DomainError(Exception):
    code: str = "domain_error"
    status_code: int = 500
    title: str = "Domain error"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class IdentityInvariantError(RuntimeError):
    """Persisted state contradicts an invariant that should be
    structurally impossible given currently designed features."""

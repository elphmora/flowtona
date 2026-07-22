"""
app/api/schemas/auth.py

HTTP request/response schemas for signup, login, tenant selection,
refresh, and logout. Domain models never get serialized directly to a
client — every response here is a dedicated projection (User carries
password_hash, which must never leave the service boundary).

Scoped to exactly what these route PRs need. Verification and
invitation schemas are added in their own PRs, alongside the routes
that actually use them.
"""

from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field, StringConstraints, field_validator
from app.constants.roles import Role


def _reject_blank_password(value: str) -> str:
    """Reject passwords consisting entirely of whitespace, without
    modifying legitimate password content."""
    if not value.strip():
        raise ValueError("must not be entirely whitespace")
    return value


# --- Shared response projections ---
class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    display_name: str
    email_verified: bool


class TenantResponse(BaseModel):
    id: UUID
    tenant_label: str


class MembershipResponse(BaseModel):
    role: Role
    permissions_version: int


# --- Authentication outcomes ---
#
# login() can return either shape below over the SAME 200 OK status —
# disambiguated via `result` (a discriminated union), not the status
# code, since there's no standard HTTP status for "pick an account."
# Most routes (signup, refresh, select-tenant) only ever produce
# AuthenticatedSessionResponse and never need to disambiguate anything.
class AuthenticatedSessionResponse(BaseModel):
    result: Literal["authenticated"] = "authenticated"
    user: UserResponse
    tenant: TenantResponse
    membership: MembershipResponse
    access_token: str
    refresh_token: str


class TenantSelectionRequiredResponse(BaseModel):
    result: Literal["tenant_selection_required"] = "tenant_selection_required"
    user: UserResponse
    preauth_token: str


LoginResponseBody = Annotated[
    AuthenticatedSessionResponse | TenantSelectionRequiredResponse,
    Field(discriminator="result"),
]


class LogoutAllResponse(BaseModel):
    """logout_all_for_tenant() returns a bare int (the revoked-session
    count) — this gives it a named field instead of a bare integer
    body, consistent with every other response in this API being a
    JSON object."""

    revoked_count: int


# --- Request bodies ---
#
# Non-password string fields use StringConstraints(strip_whitespace=
# True, ...) directly — trimming incidental whitespace is clearly fine
# for a display name, tenant label, or token. Password fields use
# _reject_blank_password instead of strip_whitespace=True, which would
# MUTATE the value before it reaches hashing/verification — a password
# that merely contains whitespace as real content must not be silently
# rewritten, only an entirely-whitespace one rejected.
class SignupRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=8, max_length=256)]
    display_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    tenant_label: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    _validate_password = field_validator("password")(_reject_blank_password)


class LoginRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, StringConstraints(min_length=1, max_length=256)]
    _validate_password = field_validator("password")(_reject_blank_password)


class SelectTenantRequest(BaseModel):
    preauth_token: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1)
    ]
    tenant_id: UUID


class RefreshRequest(BaseModel):
    refresh_token: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1)
    ]


class LogoutRequest(BaseModel):
    refresh_token: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1)
    ]

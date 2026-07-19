"""
app/services/auth_email_sender.py

Outbound email port for AuthService — deliberately specific to the two
business events AuthService needs to communicate (verification,
invitation), not a generic send_email(to, subject, body). A generic
protocol would make AuthService responsible for composing subject
lines and body copy, which is a presentation concern that belongs to
whatever adapter implements this — AuthService only ever announces
that a business event happened, never how it should read.

No real implementation exists yet — Phase 1's adapter can be a no-op/
log-only stand-in (matches the ElphMoraSim plan, where most personas
never verify anyway), with a real email-sending implementation to
follow once one is actually needed.
"""

from typing import Protocol

from app.models.tenant import Tenant
from app.models.user import User


class AuthEmailSender(Protocol):
    async def send_verification_email(self, *, to: str, raw_token: str) -> None:
        """Called after signup and after resend_verification_email().
        The adapter owns constructing the actual verification URL from
        raw_token and rendering whatever template/copy it uses."""
        ...

    async def send_invitation_email(
        self, *, to: str, raw_token: str, tenant: Tenant, invited_by: User
    ) -> None:
        """Called after create_invite(). tenant and invited_by are
        passed through for the adapter's own copy (e.g. "X invited you
        to join Y") — AuthService doesn't know or care what the email
        actually says."""
        ...

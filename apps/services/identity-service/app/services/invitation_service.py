"""
app/services/invitation_service.py

Invitation lifecycle operations. Owns invitation creation, validation,
and acceptance's atomic transition — NOT the cross-service acceptance
workflow (get/create User, create Membership), which is AuthService's
job, mirroring the same boundary already established for
EmailVerificationService. No resend/revoke methods — neither is a
designed feature.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.constants.roles import Role
from app.core.config import settings
from app.exceptions.invitation import InvitationExpiredError, InvitationInvalidError
from app.models.invitation import Invitation, InvitationStatus
from app.repositories.exceptions import ConcurrentUpdateError
from app.repositories.invitation_repository import InvitationRepository
from app.security.hashing import generate_secure_token, hash_token


class InvitationService:
    def __init__(self, invitation_repo: InvitationRepository) -> None:
        self._invitation_repo = invitation_repo

    async def create(
        self,
        *,
        tenant_id: UUID,
        email: str,
        role: Role,
        invited_by_user_id: UUID,
    ) -> tuple[Invitation, str]:
        """Generates a raw token, hashes it, persists the hash, returns
        (invitation, RAW token) — the caller (AuthService) delivers the
        raw token via email. No duplicate-pending-invite check here —
        InvitationRepository only enforces token_hash uniqueness
        (trivially unique by construction); (tenant_id, email)
        uniqueness for pending invites is a genuinely open question,
        not yet decided anywhere (see the ADR)."""
        raw_token = generate_secure_token()
        token_hash = hash_token(raw_token)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=settings.INVITATION_TOKEN_EXPIRE_DAYS)
        invitation = await self._invitation_repo.create(
            tenant_id=tenant_id,
            email=email,
            role=role,
            token_hash=token_hash,
            invited_by_user_id=invited_by_user_id,
            expires_at=expires_at,
        )
        return invitation, raw_token

    async def resolve_pending(self, *, raw_token: str) -> Invitation:
        """Return the valid pending invitation for a raw token without
        consuming it. Pre-checks status/expiry for precise domain
        exceptions; the repository's mark_accepted() remains the actual
        final guard when that's eventually called separately."""
        token_hash = hash_token(raw_token)
        invitation = await self._invitation_repo.get_by_token_hash(
            token_hash=token_hash
        )
        if invitation is None:
            raise InvitationInvalidError()

        if invitation.status != InvitationStatus.PENDING:
            raise InvitationInvalidError()

        if invitation.expires_at <= datetime.now(timezone.utc):
            raise InvitationExpiredError()

        return invitation

    async def mark_accepted(
        self, *, invitation_id: UUID, accepted_at: datetime
    ) -> Invitation:
        """Thin delegation to the repository's atomic pending-and-
        unexpired guard. A lost race here (e.g. the invite expired or
        was somehow accepted between resolve_pending() and this call)
        collapses to the generic invalid-invitation error rather than
        trying to distinguish exactly why — same reasoning as
        EmailVerificationService.verify()'s race-window handling."""
        try:
            return await self._invitation_repo.mark_accepted(
                invitation_id=invitation_id, accepted_at=accepted_at
            )
        except ConcurrentUpdateError as exc:
            raise InvitationInvalidError() from exc

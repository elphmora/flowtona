"""
app/services/user_service.py

Owns user lifecycle business operations — create, verify, lookup.
Does NOT mint access or refresh tokens (that's TokenService/
RefreshTokenService's job) and does NOT orchestrate multi-service
workflows (that's AuthService's job) — this service's job is just
"the things that are true about one User."

create() order is deliberate: check-then-hash-then-create, not
hash-then-check. Argon2id is expensive by design (Decision 7) — no
reason to pay that cost for an email that's already known to be taken.
The pre-check is a UX/performance optimization only, NOT the actual
uniqueness guarantee: two near-simultaneous signups could both pass
the pre-check (both see no existing user), so create() still catches
UserRepository's DuplicateEntryError as the real, race-safe final
guard. Both paths translate to the same domain exception.
"""

from uuid import UUID

from app.exceptions.base import IdentityInvariantError
from app.exceptions.user import EmailAlreadyRegisteredError
from app.models.user import User
from app.repositories.exceptions import DuplicateEntryError
from app.repositories.user_repository import UserRepository
from app.security.hashing import hash_password


class UserService:
    def __init__(self, user_repo: UserRepository) -> None:
        self._user_repo = user_repo

    async def create(
        self,
        *,
        email: str,
        password: str,
        display_name: str,
        email_verified: bool = False,
    ) -> User:
        """email_verified defaults False (normal signup, Flow 1). Callers
        pass True only for the invitation-acceptance-by-a-new-user path
        (Invariant 9) — this service doesn't decide that policy, it just
        accepts what the caller (AuthService/InvitationService) already
        determined."""
        existing = await self._user_repo.get_by_email(email=email)
        if existing is not None:
            raise EmailAlreadyRegisteredError(email=email)

        password_hash = hash_password(password)

        try:
            return await self._user_repo.create(
                email=email,
                password_hash=password_hash,
                display_name=display_name,
                email_verified=email_verified,
            )
        except DuplicateEntryError as exc:
            # The race window the pre-check can't close: two
            # near-simultaneous signups both passing get_by_email()
            # before either reaches create().
            raise EmailAlreadyRegisteredError(email=email) from exc

    async def get_by_id(self, *, user_id: UUID) -> User | None:
        return await self._user_repo.get_by_id(user_id=user_id)

    async def get_by_email(self, *, email: str) -> User | None:
        return await self._user_repo.get_by_email(email=email)

    async def mark_email_verified(self, *, user_id: UUID, expected_email: str) -> User:
        """Flips email_verified=True. This method's contract is narrower
        than a generic lookup: it's only ever called with a user_id
        resolved from an already-consumed EmailVerification record, so
        unlike get_by_id() (where None is a normal, expected outcome),
        a missing user here means persisted state contradicts an
        invariant that should be impossible — not a normal service
        outcome, hence IdentityInvariantError rather than returning None
        or raising a DomainError with an RFC 9457 mapping.

        expected_email is the same category of guard: currently
        unreachable in practice (no email-change feature exists — see
        models/email_verification.py's docstring), but cheap to check
        and catches any future inconsistency rather than silently
        verifying against the wrong email.

        Idempotent: calling this on an already-verified user is a no-op
        that returns the user unchanged, rather than an error — a
        legitimate outcome if this is ever called twice defensively."""
        user = await self._user_repo.get_by_id(user_id=user_id)
        if user is None:
            raise IdentityInvariantError(
                f"Email verification references missing user {user_id}"
            )

        if user.email != expected_email:
            raise IdentityInvariantError(
                f"Verification email {expected_email!r} does not match "
                f"user {user_id}'s current email {user.email!r}"
            )

        if user.email_verified:
            return user

        data = user.model_dump()
        data["email_verified"] = True
        updated = User(**data)
        return await self._user_repo.update(user=updated)

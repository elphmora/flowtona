"""
app/repositories/in_memory/invitation_repository.py

In-memory implementation of InvitationRepository (Protocol, Decision 9).

email is normalized the same way as UserRepository and
EmailVerificationRepository (app/utils/email.py) — added 2026-07-14 as a
fix, not an original design choice: an earlier draft of this file stored
the raw, unnormalized email, which would have broken any email-matching
comparison on casing alone (e.g. Flow 7's guard that an authenticated
user's email matches the invite's target email).

Only token_hash uniqueness is enforced at creation — no
(tenant_id, email) uniqueness rule exists yet (see ADR: "Open, not yet
decided" — this is a genuine open question, not an oversight).

mark_accepted() atomically requires status == PENDING AND
expires_at > accepted_at, reconstructing through the constructor via
model_dump() (default python mode — NOT mode="json", which would
convert UUIDs/enums/datetimes to plain strings and break direct
reconstruction) + override + Invitation(**data). Never
model_copy(update=...), which does not re-run Pydantic validators and
would silently defeat the mutual-exclusivity/required-field validation
this model depends on.

Deliberately does not add invite revocation or resend — neither is a
designed feature (InvitationStatus has no REVOKED state; see ADR).
"""

from datetime import datetime, timezone
from uuid import UUID

from app.constants.roles import Role
from app.models.invitation import Invitation, InvitationStatus
from app.repositories.exceptions import (
    ConcurrentUpdateError,
    DuplicateEntryError,
    RecordNotFoundError,
)
from app.repositories.in_memory.store import InMemoryIdentityStore
from app.utils.email import normalise_email


class InMemoryInvitationRepository:
    def __init__(self, store: InMemoryIdentityStore) -> None:
        self._store = store

    async def create(
        self,
        *,
        tenant_id: UUID,
        email: str,
        role: Role,
        token_hash: str,
        invited_by_user_id: UUID,
        expires_at: datetime,
    ) -> Invitation:
        normalized = normalise_email(email)

        async with self._store.lock:
            if token_hash in self._store.invitation_id_by_token_hash:
                raise DuplicateEntryError(entity="invitation", field="token_hash")

            invitation = Invitation(
                tenant_id=tenant_id,
                email=normalized,
                role=role,
                token_hash=token_hash,
                invited_by_user_id=invited_by_user_id,
                created_at=datetime.now(timezone.utc),
                expires_at=expires_at,
            )
            stored = invitation.model_copy(deep=True)
            self._store.invitations_by_id[invitation.id] = stored
            self._store.invitation_id_by_token_hash[token_hash] = invitation.id
            return stored.model_copy(deep=True)

    async def get_by_token_hash(self, *, token_hash: str) -> Invitation | None:
        invitation_id = self._store.invitation_id_by_token_hash.get(token_hash)
        if invitation_id is None:
            return None
        return self._store.invitations_by_id[invitation_id].model_copy(deep=True)

    async def mark_accepted(
        self, *, invitation_id: UUID, accepted_at: datetime
    ) -> Invitation:
        async with self._store.lock:
            invitation = self._store.invitations_by_id.get(invitation_id)
            if invitation is None:
                raise RecordNotFoundError(entity="invitation", identifier=invitation_id)

            if invitation.status != InvitationStatus.PENDING:
                raise ConcurrentUpdateError(
                    entity="invitation",
                    identifier=invitation_id,
                    expected_state="pending",
                    actual_state=invitation.status.value,
                )

            if invitation.expires_at <= accepted_at:
                raise ConcurrentUpdateError(
                    entity="invitation",
                    identifier=invitation_id,
                    expected_state="unexpired",
                    actual_state="expired",
                )

            data = invitation.model_dump()
            data["status"] = InvitationStatus.ACCEPTED
            data["accepted_at"] = accepted_at
            updated = Invitation(**data)

            self._store.invitations_by_id[invitation_id] = updated.model_copy(deep=True)
            return updated.model_copy(deep=True)

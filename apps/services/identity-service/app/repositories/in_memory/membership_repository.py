"""
app/repositories/in_memory/membership_repository.py

In-memory implementation of MembershipRepository (Protocol, Decision 9).

create() checks (user_id, tenant_id) uniqueness, creates the membership,
and appends to membership_ids_by_user — all inside one lock acquisition,
in that order, so the list can never gain an entry for a membership that
failed its uniqueness check.

update() rejects any attempt to change user_id or tenant_id — those
fields define the membership's identity and its index keys
(membership_id_by_user_tenant, membership_ids_by_user). Silently
rewriting indexes to follow a changed identity field is exactly the kind
of thing that quietly corrupts a store; better to refuse outright.
"""

from datetime import datetime, timezone
from uuid import UUID

from app.constants.roles import Role
from app.models.membership import TenantMembership
from app.repositories.exceptions import DuplicateEntryError, RecordNotFoundError
from app.repositories.in_memory.store import InMemoryIdentityStore


class InMemoryMembershipRepository:
    def __init__(self, store: InMemoryIdentityStore) -> None:
        self._store = store

    async def create(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
        role: Role,
    ) -> TenantMembership:
        async with self._store.lock:
            key = (user_id, tenant_id)
            if key in self._store.membership_id_by_user_tenant:
                raise DuplicateEntryError(entity="membership", field="user_tenant")

            membership = TenantMembership(
                user_id=user_id,
                tenant_id=tenant_id,
                role=role,
                created_at=datetime.now(timezone.utc),
            )
            stored = membership.model_copy(deep=True)
            self._store.memberships_by_id[membership.id] = stored
            self._store.membership_id_by_user_tenant[key] = membership.id
            self._store.membership_ids_by_user.setdefault(user_id, []).append(
                membership.id
            )
            return stored.model_copy(deep=True)

    async def get_by_user_and_tenant(
        self, *, user_id: UUID, tenant_id: UUID
    ) -> TenantMembership | None:
        membership_id = self._store.membership_id_by_user_tenant.get(
            (user_id, tenant_id)
        )
        if membership_id is None:
            return None
        return self._store.memberships_by_id[membership_id].model_copy(deep=True)

    async def get_memberships_for_user(
        self, *, user_id: UUID
    ) -> list[TenantMembership]:
        ids = self._store.membership_ids_by_user.get(user_id, [])
        return [self._store.memberships_by_id[i].model_copy(deep=True) for i in ids]

    async def update(self, *, membership: TenantMembership) -> TenantMembership:
        async with self._store.lock:
            existing = self._store.memberships_by_id.get(membership.id)
            if existing is None:
                raise RecordNotFoundError(entity="membership", identifier=membership.id)

            if (
                existing.user_id != membership.user_id
                or existing.tenant_id != membership.tenant_id
            ):
                raise NotImplementedError(
                    "Changing user_id or tenant_id via update() is not "
                    "supported — those fields define this membership's "
                    "identity and index keys."
                )

            self._store.memberships_by_id[membership.id] = membership.model_copy(
                deep=True
            )
            return membership.model_copy(deep=True)

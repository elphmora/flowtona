"""
app/services/membership_service.py

Membership lifecycle operations. Translates duplicate repository
entries into domain errors; permissions_version bumps are delegated to
the repository's atomic bulk operation (see
MembershipRepository.bump_permissions_version_for_user()) rather than
looped here, to avoid lost updates and partial completion once this is
backed by a real database.

Deliberately narrow — no suspend/revoke/change-role methods, since no
designed endpoint in 01-api-contract.md calls any of those yet.
"""

from uuid import UUID

from app.constants.roles import Role
from app.exceptions.membership import AlreadyAMemberError
from app.models.membership import TenantMembership
from app.repositories.exceptions import DuplicateEntryError
from app.repositories.membership_repository import MembershipRepository


class MembershipService:
    def __init__(self, membership_repo: MembershipRepository) -> None:
        self._membership_repo = membership_repo

    async def create(
        self, *, user_id: UUID, tenant_id: UUID, role: Role
    ) -> TenantMembership:
        try:
            return await self._membership_repo.create(
                user_id=user_id, tenant_id=tenant_id, role=role
            )
        except DuplicateEntryError as exc:
            raise AlreadyAMemberError() from exc

    async def get_by_user_and_tenant(
        self, *, user_id: UUID, tenant_id: UUID
    ) -> TenantMembership | None:
        return await self._membership_repo.get_by_user_and_tenant(
            user_id=user_id, tenant_id=tenant_id
        )

    async def get_memberships_for_user(
        self, *, user_id: UUID
    ) -> list[TenantMembership]:
        return await self._membership_repo.get_memberships_for_user(user_id=user_id)

    async def bump_permissions_version_for_user(
        self, *, user_id: UUID
    ) -> list[TenantMembership]:
        return await self._membership_repo.bump_permissions_version_for_user(
            user_id=user_id
        )

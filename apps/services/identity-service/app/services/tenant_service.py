"""
app/services/tenant_service.py

Owns tenant lifecycle business operations — currently just create and
lookup, matching TenantRepository's deliberately minimal surface
(Decision 1: identity-service only ever creates and reads a Tenant's
id + tenant_label; no update method, no uniqueness constraint on
tenant_label — see the ADR's "Open, not yet decided" note, and don't
invent one here).

tenant_label validation (non-empty after stripping) lives HERE, not in
the repository. Contrast with User/EmailVerification/Invitation's
email normalization, which lives in the repository because it's
required for INDEX correctness (the email-uniqueness dict needs
consistent keys). tenant_label has no uniqueness index to protect —
this is pure business-rule validation ("a tenant needs a real label"),
which is what makes this a genuine service, not a passthrough wrapper
around a two-method repository.
"""

from uuid import UUID

from app.exceptions.tenant import InvalidTenantLabelError
from app.models.tenant import Tenant
from app.repositories.tenant_repository import TenantRepository


class TenantService:
    def __init__(self, tenant_repo: TenantRepository) -> None:
        self._tenant_repo = tenant_repo

    async def create(self, *, tenant_label: str) -> Tenant:
        stripped = tenant_label.strip()
        if not stripped:
            raise InvalidTenantLabelError()
        return await self._tenant_repo.create(tenant_label=stripped)

    async def get_by_id(self, *, tenant_id: UUID) -> Tenant | None:
        return await self._tenant_repo.get_by_id(tenant_id=tenant_id)

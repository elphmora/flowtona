"""tests/unit/services/test_tenant_service.py"""

from uuid import uuid4

import pytest

from app.exceptions.tenant import InvalidTenantLabelError
from app.services.tenant_service import TenantService

pytestmark = pytest.mark.asyncio


@pytest.fixture
def service(tenant_repo) -> TenantService:
    return TenantService(tenant_repo)


class TestCreate:
    async def test_creates_tenant_with_given_label(self, service):
        tenant = await service.create(tenant_label="Birmingham Plumbing Co.")
        assert tenant.tenant_label == "Birmingham Plumbing Co."

    async def test_strips_leading_and_trailing_whitespace(self, service):
        tenant = await service.create(tenant_label="  Birmingham Plumbing Co.  ")
        assert tenant.tenant_label == "Birmingham Plumbing Co."

    async def test_rejects_empty_label(self, service):
        with pytest.raises(InvalidTenantLabelError):
            await service.create(tenant_label="")

    async def test_rejects_whitespace_only_label(self, service):
        with pytest.raises(InvalidTenantLabelError):
            await service.create(tenant_label="   ")

    async def test_no_uniqueness_constraint_on_label(self, service):
        """Confirms the deliberate absence of a uniqueness rule — two
        tenants may share a display label without conflict (see ADR:
        "Open, not yet decided" on tenant_label uniqueness)."""
        t1 = await service.create(tenant_label="Plumbing Co.")
        t2 = await service.create(tenant_label="Plumbing Co.")
        assert t1.id != t2.id


class TestGetById:
    async def test_roundtrip(self, service):
        created = await service.create(tenant_label="Birmingham Plumbing Co.")
        fetched = await service.get_by_id(tenant_id=created.id)
        assert fetched.id == created.id
        assert fetched.tenant_label == "Birmingham Plumbing Co."

    async def test_returns_none_for_unknown_tenant(self, service):
        assert await service.get_by_id(tenant_id=uuid4()) is None

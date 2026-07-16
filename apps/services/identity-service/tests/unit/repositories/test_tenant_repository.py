"""tests/unit/repositories/test_tenant_repository.py"""

import pytest


@pytest.mark.asyncio
async def test_create_and_get_roundtrip(tenant_repo):
    tenant = await tenant_repo.create(tenant_label="Birmingham Plumbing Co.")
    fetched = await tenant_repo.get_by_id(tenant_id=tenant.id)
    assert fetched.id == tenant.id
    assert fetched.tenant_label == "Birmingham Plumbing Co."


@pytest.mark.asyncio
async def test_no_uniqueness_constraint_on_label(tenant_repo):
    """No uniqueness rule exists on tenant_label — two tenants may share
    a display label without conflict."""
    t1 = await tenant_repo.create(tenant_label="Plumbing Co.")
    t2 = await tenant_repo.create(tenant_label="Plumbing Co.")
    assert t1.id != t2.id

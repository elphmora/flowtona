"""
tests/integration/auth_helpers.py

Plumbing shared across integration test modules — not business
behavior (unlike resource creation, which stays inlined at each call
site per test_clients_api.py's own docstring), just repetitive setup
every module needs.
"""

from tests.unit.auth_fixtures import make_token


def auth_header(
    private_key, *, tenant_id: str, permissions: list[str]
) -> dict[str, str]:
    token = make_token(private_key, tenant_id=tenant_id, permissions=permissions)
    return {"Authorization": f"Bearer {token}"}

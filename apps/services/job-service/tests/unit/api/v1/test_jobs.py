"""
tests/unit/api/v1/test_jobs.py

Composition tests for the /v1/jobs HTTP surface.

These tests are the point where authentication, tenant derivation,
authorization, service orchestration, persistence, response mapping,
and RFC 9457 error translation run together as real request paths,
rather than as independently mocked units.

Two real pieces are assembled per test, matching the actual dependency
graph rather than re-mocking job-service's own already-tested
components:
  - A real signed ES256 JWT, verified through the REAL TokenVerifier
    inside the real app (JWKS resolution monkeypatched at the
    PyJWKClient class level, autouse -- the authentication-boundary
    network lookup is replaced using the same technique already proven
    in test_token_verifier.py; there is no separate TokenVerifier
    injection seam since create_app() constructs it internally).
  - A real JobService + real InMemoryJobRepository + real
    ClientServiceClient, the last one given an httpx.MockTransport
    simulating Client Service's HTTP responses -- the other replaced
    network boundary, the same one test_client_service_client.py
    already faked, not re-invented here. Assembled into a real
    ServiceRegistry, injected via create_app(registry=...) -- the
    actual DI seam Phase 0 built for this.

Deliberately NOT tested here: TokenVerifier.verify() being called
exactly once across get_access_token() + both require_permission(...)
checks. That's a real architectural property the route's design
relies on, but asserting it directly would mean either patching
TokenVerifier internals or coupling this suite to FastAPI's dependency-
cache implementation detail rather than the actual request-path
behavior these tests exist to prove.
"""

from __future__ import annotations

import time
import uuid
from typing import Any
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientError

from app.api.dependencies import ServiceRegistry
from app.core.config import Settings
from app.main import create_app
from app.models.job import Job, JobStatus, SiteAddressSnapshot
from app.repositories.in_memory.job_repository import InMemoryJobRepository
from app.services.client_service_client import ClientServiceClient
from app.services.job_service import JobService

_KID = "test-key-1"
_ISSUER = "https://identity.flowtona.dev"
_AUDIENCE = "flowtona-api"


class _FakeSigningKey:
    def __init__(self, key: Any) -> None:
        self.key = key


@pytest.fixture(scope="module")
def keypair() -> ec.EllipticCurvePrivateKey:
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture(autouse=True)
def _patch_jwks_resolution(
    keypair: ec.EllipticCurvePrivateKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reaches whatever TokenVerifier create_app()'s lifespan
    constructs internally -- see module docstring."""
    public_key = keypair.public_key()

    def _fake_get_signing_key_from_jwt(
        self: PyJWKClient, token: str
    ) -> _FakeSigningKey:
        header = jwt.get_unverified_header(token)
        if header.get("kid") != _KID:
            raise PyJWKClientError(
                f"Unable to find a signing key matching {header.get('kid')!r}"
            )
        return _FakeSigningKey(public_key)

    monkeypatch.setattr(
        PyJWKClient, "get_signing_key_from_jwt", _fake_get_signing_key_from_jwt
    )


def _make_token(
    keypair: ec.EllipticCurvePrivateKey,
    *,
    tenant_id: UUID | None = None,
    permissions: list[str] | None = None,
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": _ISSUER,
        "aud": _AUDIENCE,
        "sub": str(uuid.uuid4()),
        "tenant_id": str(tenant_id or uuid.uuid4()),
        "role": "dispatcher",
        "permissions": permissions
        if permissions is not None
        else ["jobs:write", "clients:read"],
        "permissions_version": 1,
        "token_type": "access",
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + 3600,
    }
    return jwt.encode(claims, keypair, algorithm="ES256", headers={"kid": _KID})


def _client_service_payload(
    client_id: UUID, site_id: UUID, contact_id: UUID, *, status: str = "active"
) -> dict[str, Any]:
    return {
        "id": str(client_id),
        "name": "Birmingham Plumbing Co.",
        "status": status,
        "sites": [
            {
                "id": str(site_id),
                "label": "Main Warehouse",
                "address": {
                    "line1": "14 Colmore Row",
                    "line2": None,
                    "city": "Birmingham",
                    "postcode": "B3 2QD",
                    "country": None,
                },
            }
        ],
        "contacts": [
            {
                "id": str(contact_id),
                "name": "Priya Shah",
                "email": "priya@birminghamplumbing.co.uk",
                "phone": "+44 121 000 0000",
            }
        ],
    }


def _build_app(*, client_service_handler: Any) -> tuple[Any, ServiceRegistry]:
    """Assembles a real ServiceRegistry (real JobService, real
    InMemoryJobRepository, real ClientServiceClient with a mocked
    transport) and injects it via create_app(registry=...)."""
    settings = Settings()
    repository = InMemoryJobRepository()
    client = ClientServiceClient(
        base_url="http://client-service:8000",
        transport=httpx.MockTransport(client_service_handler),
    )
    job_service = JobService(client, repository)
    registry = ServiceRegistry(job_repository=repository, job_service=job_service)
    app = create_app(settings=settings, registry=registry)
    return app, registry


def _valid_request_body(
    client_id: UUID, site_id: UUID, contact_id: UUID
) -> dict[str, Any]:
    return {
        "client_id": str(client_id),
        "site_id": str(site_id),
        "contact_id": str(contact_id),
        "title": "Annual boiler service",
        "description": "Client reports intermittent pilot light failure.",
    }


def _make_job(tenant_id: UUID | None = None, **overrides: Any) -> Job:
    """For seeding the repository directly in Query Operations tests
    -- these routes are read-only, so there's no reason to route every
    test through a full POST /v1/jobs composition just to get a Job to
    read back. **overrides lets a test set e.g. status=JobStatus.CANCELLED
    or client_id=some_specific_id after construction, matching the same
    direct-attribute-assignment pattern already used in
    test_in_memory_job_repository.py and test_job_service.py."""
    job = Job.create(
        tenant_id=tenant_id or uuid4(),
        client_id=uuid4(),
        client_name_snapshot="Birmingham Plumbing Co.",
        site_id=uuid4(),
        site_label_snapshot="Main Warehouse",
        site_address_snapshot=SiteAddressSnapshot(
            line1="14 Colmore Row", city="Birmingham", postcode="B3 2QD"
        ),
        title="Annual boiler service",
    )
    for key, value in overrides.items():
        setattr(job, key, value)
    return job


def _unused_client_service_handler(request: httpx.Request) -> httpx.Response:
    """Query Operations never call Client Service (03-api-contract.md:
    all three GET routes require only jobs:read). Raising here, rather
    than just not caring, makes any such fault fail loudly and
    immediately rather than silently returning a plausible-looking
    fake response that would mask the bug."""
    raise AssertionError(
        "Client Service was called during a Query Operations test -- "
        "these routes should never make an outbound call."
    )


# ---------------------------------------------------------------------------
# 1. Successful composition
# ---------------------------------------------------------------------------


async def test_create_job_succeeds_with_full_composition(
    keypair: ec.EllipticCurvePrivateKey,
) -> None:
    tenant_id = uuid4()
    client_id, site_id, contact_id = uuid4(), uuid4(), uuid4()
    seen_auth_headers: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth_headers.append(request.headers["authorization"])
        return httpx.Response(
            200, json=_client_service_payload(client_id, site_id, contact_id)
        )

    app, registry = _build_app(client_service_handler=handler)
    token = _make_token(keypair, tenant_id=tenant_id)

    with TestClient(app) as client:
        response = client.post(
            "/v1/jobs",
            json=_valid_request_body(client_id, site_id, contact_id),
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "draft"
    assert body["visits"] == []
    assert body["tenant_id"] == str(tenant_id)
    assert body["client_id"] == str(client_id)
    assert body["client_name_snapshot"] == "Birmingham Plumbing Co."
    assert body["site_id"] == str(site_id)
    assert body["site_label_snapshot"] == "Main Warehouse"
    assert body["site_address_snapshot"]["city"] == "Birmingham"
    assert body["contact_id"] == str(contact_id)
    assert body["contact_name_snapshot"] == "Priya Shah"
    assert body["contact_email_snapshot"] == "priya@birminghamplumbing.co.uk"
    assert body["created_at"] == body["updated_at"]

    # Exact original bearer token reached Client Service, unchanged.
    assert seen_auth_headers == [f"Bearer {token}"]

    # Created Job exists in the application-scoped repository.
    persisted = await registry.job_repository.get(
        tenant_id=tenant_id, job_id=UUID(body["id"])
    )
    assert persisted is not None
    assert persisted.title == "Annual boiler service"


# ---------------------------------------------------------------------------
# 2. HTTP boundary enforcement
# ---------------------------------------------------------------------------


async def test_create_job_rejects_body_supplied_tenant_id(
    keypair: ec.EllipticCurvePrivateKey,
) -> None:
    client_id, site_id, contact_id = uuid4(), uuid4(), uuid4()
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(
            200, json=_client_service_payload(client_id, site_id, contact_id)
        )

    app, _ = _build_app(client_service_handler=handler)
    token = _make_token(keypair)
    body = _valid_request_body(client_id, site_id, contact_id)
    body["tenant_id"] = str(uuid4())  # attempted injection

    with TestClient(app) as client:
        response = client.post(
            "/v1/jobs", json=body, headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"
    assert calls["count"] == 0


async def test_create_job_rejects_blank_title(
    keypair: ec.EllipticCurvePrivateKey,
) -> None:
    client_id, site_id, contact_id = uuid4(), uuid4(), uuid4()
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(
            200, json=_client_service_payload(client_id, site_id, contact_id)
        )

    app, _ = _build_app(client_service_handler=handler)
    token = _make_token(keypair)
    body = _valid_request_body(client_id, site_id, contact_id)
    body["title"] = "   "

    with TestClient(app) as client:
        response = client.post(
            "/v1/jobs", json=body, headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"
    assert calls["count"] == 0


# ---------------------------------------------------------------------------
# 3. Authentication/authorization fail-fast
# ---------------------------------------------------------------------------


async def test_create_job_rejects_missing_jwt() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={})

    app, _ = _build_app(client_service_handler=handler)

    with TestClient(app) as client:
        response = client.post(
            "/v1/jobs", json=_valid_request_body(uuid4(), uuid4(), uuid4())
        )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert calls["count"] == 0


async def test_create_job_rejects_invalid_jwt() -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={})

    app, _ = _build_app(client_service_handler=handler)

    with TestClient(app) as client:
        response = client.post(
            "/v1/jobs",
            json=_valid_request_body(uuid4(), uuid4(), uuid4()),
            headers={"Authorization": "Bearer not-a-real-jwt"},
        )

    assert response.status_code == 401
    assert calls["count"] == 0


async def test_create_job_rejects_missing_jobs_write_permission(
    keypair: ec.EllipticCurvePrivateKey,
) -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={})

    app, _ = _build_app(client_service_handler=handler)
    token = _make_token(keypair, permissions=["clients:read"])  # missing jobs:write

    with TestClient(app) as client:
        response = client.post(
            "/v1/jobs",
            json=_valid_request_body(uuid4(), uuid4(), uuid4()),
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 403
    assert calls["count"] == 0


async def test_create_job_rejects_missing_clients_read_permission(
    keypair: ec.EllipticCurvePrivateKey,
) -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={})

    app, _ = _build_app(client_service_handler=handler)
    token = _make_token(keypair, permissions=["jobs:write"])  # missing clients:read

    with TestClient(app) as client:
        response = client.post(
            "/v1/jobs",
            json=_valid_request_body(uuid4(), uuid4(), uuid4()),
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 403
    assert calls["count"] == 0


# ---------------------------------------------------------------------------
# 4. Downstream/domain translation and lifecycle
# ---------------------------------------------------------------------------


async def test_create_job_translates_client_not_found(
    keypair: ec.EllipticCurvePrivateKey,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    app, _ = _build_app(client_service_handler=handler)
    token = _make_token(keypair)

    with TestClient(app) as client:
        response = client.post(
            "/v1/jobs",
            json=_valid_request_body(uuid4(), uuid4(), uuid4()),
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "client_not_found"
    assert body["type"].endswith("/client-not-found")
    assert body["request_id"]


async def test_create_job_translates_client_service_unavailable(
    keypair: ec.EllipticCurvePrivateKey,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated connection failure", request=request)

    app, _ = _build_app(client_service_handler=handler)
    token = _make_token(keypair)

    with TestClient(app) as client:
        response = client.post(
            "/v1/jobs",
            json=_valid_request_body(uuid4(), uuid4(), uuid4()),
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 503
    assert response.json()["code"] == "client_service_unavailable"


async def test_two_requests_share_the_same_repository(
    keypair: ec.EllipticCurvePrivateKey,
) -> None:
    """The composition-root property this whole checkpoint depends on:
    the injected registry holds ONE InMemoryJobRepository, reused for
    the application's lifetime, not reconstructed per request. Proven
    by creating two Jobs through two separate requests and confirming
    BOTH are retrievable from the same registry-held repository --
    not by adding a GET endpoint that doesn't exist yet in Phase 1."""
    tenant_id = uuid4()
    ids_by_client = {uuid4(): (uuid4(), uuid4()), uuid4(): (uuid4(), uuid4())}
    client_ids = list(ids_by_client.keys())

    def handler(request: httpx.Request) -> httpx.Response:
        requested_client_id = UUID(request.url.path.rsplit("/", 1)[-1])
        site_id, contact_id = ids_by_client[requested_client_id]
        return httpx.Response(
            200, json=_client_service_payload(requested_client_id, site_id, contact_id)
        )

    app, registry = _build_app(client_service_handler=handler)
    token = _make_token(keypair, tenant_id=tenant_id)

    responses = []
    with TestClient(app) as client:
        for client_id in client_ids:
            site_id, contact_id = ids_by_client[client_id]
            response = client.post(
                "/v1/jobs",
                json=_valid_request_body(client_id, site_id, contact_id),
                headers={"Authorization": f"Bearer {token}"},
            )
            responses.append(response)

    assert all(r.status_code == 201 for r in responses)

    job_ids = [UUID(r.json()["id"]) for r in responses]
    assert job_ids[0] != job_ids[1]

    for job_id in job_ids:
        persisted = await registry.job_repository.get(
            tenant_id=tenant_id, job_id=job_id
        )
        assert persisted is not None


# ---------------------------------------------------------------------------
# 5. Query Operations -- GET /v1/jobs/{job_id}
# ---------------------------------------------------------------------------


async def test_get_job_returns_full_job_when_it_exists(
    keypair: ec.EllipticCurvePrivateKey,
) -> None:
    tenant_id = uuid4()
    app, registry = _build_app(client_service_handler=_unused_client_service_handler)
    job = _make_job(tenant_id)
    await registry.job_repository.create(job)
    token = _make_token(keypair, tenant_id=tenant_id, permissions=["jobs:read"])

    with TestClient(app) as client:
        response = client.get(
            f"/v1/jobs/{job.id}", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(job.id)
    assert body["tenant_id"] == str(tenant_id)
    assert body["status"] == "draft"
    assert body["client_name_snapshot"] == "Birmingham Plumbing Co."
    assert body["site_label_snapshot"] == "Main Warehouse"
    assert body["visits"] == []


async def test_get_job_returns_404_for_unknown_job_id(
    keypair: ec.EllipticCurvePrivateKey,
) -> None:
    app, _ = _build_app(client_service_handler=_unused_client_service_handler)
    token = _make_token(keypair, permissions=["jobs:read"])

    with TestClient(app) as client:
        response = client.get(
            f"/v1/jobs/{uuid4()}", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 404
    assert response.json()["code"] == "job_not_found"


async def test_get_job_returns_404_for_job_belonging_to_a_different_tenant(
    keypair: ec.EllipticCurvePrivateKey,
) -> None:
    """Tenant non-disclosure: a genuinely-existing Job under a
    different tenant must be indistinguishable from one that doesn't
    exist at all -- same status code, same code value, no signal that
    anything exists there."""
    app, registry = _build_app(client_service_handler=_unused_client_service_handler)
    job = _make_job(uuid4())
    await registry.job_repository.create(job)
    token = _make_token(keypair, tenant_id=uuid4(), permissions=["jobs:read"])

    with TestClient(app) as client:
        response = client.get(
            f"/v1/jobs/{job.id}", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 404
    assert response.json()["code"] == "job_not_found"


async def test_get_job_requires_authentication(
    keypair: ec.EllipticCurvePrivateKey,
) -> None:
    app, _ = _build_app(client_service_handler=_unused_client_service_handler)

    with TestClient(app) as client:
        response = client.get(f"/v1/jobs/{uuid4()}")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_get_job_requires_jobs_read_permission(
    keypair: ec.EllipticCurvePrivateKey,
) -> None:
    app, _ = _build_app(client_service_handler=_unused_client_service_handler)
    token = _make_token(keypair, permissions=["jobs:write"])  # missing jobs:read

    with TestClient(app) as client:
        response = client.get(
            f"/v1/jobs/{uuid4()}", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# 6. Query Operations -- GET /v1/jobs (list)
# ---------------------------------------------------------------------------


async def test_list_jobs_returns_the_paginated_envelope(
    keypair: ec.EllipticCurvePrivateKey,
) -> None:
    tenant_id = uuid4()
    app, registry = _build_app(client_service_handler=_unused_client_service_handler)
    job = _make_job(tenant_id)
    await registry.job_repository.create(job)
    token = _make_token(keypair, tenant_id=tenant_id, permissions=["jobs:read"])

    with TestClient(app) as client:
        response = client.get("/v1/jobs", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["id"] == str(job.id)
    assert item["client_name_snapshot"] == "Birmingham Plumbing Co."
    assert item["site_label_snapshot"] == "Main Warehouse"
    assert item["visit_count"] == 0
    assert "visits" not in item  # summary shape, not the nested detail shape


async def test_list_jobs_only_returns_the_callers_tenant(
    keypair: ec.EllipticCurvePrivateKey,
) -> None:
    tenant_a = uuid4()
    tenant_b = uuid4()
    app, registry = _build_app(client_service_handler=_unused_client_service_handler)
    job_a = _make_job(tenant_a)
    job_b = _make_job(tenant_b)
    await registry.job_repository.create(job_a)
    await registry.job_repository.create(job_b)
    token = _make_token(keypair, tenant_id=tenant_a, permissions=["jobs:read"])

    with TestClient(app) as client:
        response = client.get("/v1/jobs", headers={"Authorization": f"Bearer {token}"})

    body = response.json()
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == [str(job_a.id)]


async def test_list_jobs_filters_by_status(keypair: ec.EllipticCurvePrivateKey) -> None:
    tenant_id = uuid4()
    app, registry = _build_app(client_service_handler=_unused_client_service_handler)
    draft_job = _make_job(tenant_id)
    cancelled_job = _make_job(tenant_id, status=JobStatus.CANCELLED)
    await registry.job_repository.create(draft_job)
    await registry.job_repository.create(cancelled_job)
    token = _make_token(keypair, tenant_id=tenant_id, permissions=["jobs:read"])

    with TestClient(app) as client:
        response = client.get(
            "/v1/jobs",
            params={"status": "draft"},
            headers={"Authorization": f"Bearer {token}"},
        )

    body = response.json()
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == [str(draft_job.id)]


async def test_list_jobs_filters_by_client_id(
    keypair: ec.EllipticCurvePrivateKey,
) -> None:
    tenant_id = uuid4()
    target_client_id = uuid4()
    app, registry = _build_app(client_service_handler=_unused_client_service_handler)
    matching_job = _make_job(tenant_id, client_id=target_client_id)
    other_job = _make_job(tenant_id)
    await registry.job_repository.create(matching_job)
    await registry.job_repository.create(other_job)
    token = _make_token(keypair, tenant_id=tenant_id, permissions=["jobs:read"])

    with TestClient(app) as client:
        response = client.get(
            "/v1/jobs",
            params={"client_id": str(target_client_id)},
            headers={"Authorization": f"Bearer {token}"},
        )

    body = response.json()
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == [str(matching_job.id)]


async def test_list_jobs_clamps_limit_above_the_maximum(
    keypair: ec.EllipticCurvePrivateKey,
) -> None:
    """500 is a well-formed request for more than this API is willing
    to return in one page -- clamped to 100, not rejected
    (03-api-contract.md: "default 20, max 100, clamped")."""
    app, _ = _build_app(client_service_handler=_unused_client_service_handler)
    token = _make_token(keypair, permissions=["jobs:read"])

    with TestClient(app) as client:
        response = client.get(
            "/v1/jobs",
            params={"limit": 500},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["limit"] == 100


async def test_list_jobs_rejects_non_positive_limit(
    keypair: ec.EllipticCurvePrivateKey,
) -> None:
    """A limit of 0 (or negative) is a malformed request -- 422, a
    different kind of problem than "too high" (which clamps)."""
    app, _ = _build_app(client_service_handler=_unused_client_service_handler)
    token = _make_token(keypair, permissions=["jobs:read"])

    with TestClient(app) as client:
        response = client.get(
            "/v1/jobs",
            params={"limit": 0},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 422


async def test_list_jobs_applies_limit_and_offset(
    keypair: ec.EllipticCurvePrivateKey,
) -> None:
    """Proves the full HTTP chain -- FastAPI query parsing -> route ->
    service -> repository -> envelope -- actually honors a non-default
    offset, not just that the default (offset=0) happens to work.
    Repository-level pagination is already thoroughly proven in
    test_in_memory_job_repository.py; this test is specifically about
    HTTP composition, not re-proving that logic."""
    tenant_id = uuid4()
    app, registry = _build_app(client_service_handler=_unused_client_service_handler)
    first = _make_job(tenant_id)
    second = _make_job(tenant_id)
    await registry.job_repository.create(first)
    await registry.job_repository.create(second)
    token = _make_token(keypair, tenant_id=tenant_id, permissions=["jobs:read"])

    with TestClient(app) as client:
        response = client.get(
            "/v1/jobs",
            params={"limit": 1, "offset": 1},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["limit"] == 1
    assert body["offset"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == str(second.id)


async def test_list_jobs_requires_jobs_read_permission(
    keypair: ec.EllipticCurvePrivateKey,
) -> None:
    app, _ = _build_app(client_service_handler=_unused_client_service_handler)
    token = _make_token(keypair, permissions=["jobs:write"])  # missing jobs:read

    with TestClient(app) as client:
        response = client.get("/v1/jobs", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# 7. Query Operations -- GET /v1/jobs/{job_id}/visits/{visit_id}
# ---------------------------------------------------------------------------


async def test_get_visit_returns_job_not_found_for_unknown_job_id(
    keypair: ec.EllipticCurvePrivateKey,
) -> None:
    app, _ = _build_app(client_service_handler=_unused_client_service_handler)
    token = _make_token(keypair, permissions=["jobs:read"])

    with TestClient(app) as client:
        response = client.get(
            f"/v1/jobs/{uuid4()}/visits/{uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 404
    assert response.json()["code"] == "job_not_found"


async def test_get_visit_returns_visit_not_found_when_job_exists_but_visit_does_not(
    keypair: ec.EllipticCurvePrivateKey,
) -> None:
    """The one reachable outcome today: every real Job's visits list
    is empty until Phase 2, so this is genuinely correct behavior for
    any visit_id against an otherwise-valid Job -- not a stand-in for
    an untested success case. The positive-retrieval test lands in
    Phase 2 once Visits become constructible."""
    tenant_id = uuid4()
    app, registry = _build_app(client_service_handler=_unused_client_service_handler)
    job = _make_job(tenant_id)
    await registry.job_repository.create(job)
    token = _make_token(keypair, tenant_id=tenant_id, permissions=["jobs:read"])

    with TestClient(app) as client:
        response = client.get(
            f"/v1/jobs/{job.id}/visits/{uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 404
    assert response.json()["code"] == "visit_not_found"


async def test_get_visit_returns_job_not_found_for_job_belonging_to_a_different_tenant(
    keypair: ec.EllipticCurvePrivateKey,
) -> None:
    """Cross-tenant nested-Visit lookup must produce job_not_found,
    NOT visit_not_found -- returning visit_not_found here would
    indirectly reveal that the Job itself exists under a different
    tenant, undermining the non-disclosure property already enforced
    on GET /v1/jobs/{job_id}. Tenant scoping must hold at every level
    of this nested lookup, not just the outer one."""
    tenant_a = uuid4()
    tenant_b = uuid4()
    app, registry = _build_app(client_service_handler=_unused_client_service_handler)
    job = _make_job(tenant_a)
    await registry.job_repository.create(job)
    token = _make_token(keypair, tenant_id=tenant_b, permissions=["jobs:read"])

    with TestClient(app) as client:
        response = client.get(
            f"/v1/jobs/{job.id}/visits/{uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 404
    assert response.json()["code"] == "job_not_found"


async def test_get_visit_requires_jobs_read_permission(
    keypair: ec.EllipticCurvePrivateKey,
) -> None:
    app, _ = _build_app(client_service_handler=_unused_client_service_handler)
    token = _make_token(keypair, permissions=["jobs:write"])  # missing jobs:read

    with TestClient(app) as client:
        response = client.get(
            f"/v1/jobs/{uuid4()}/visits/{uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 403

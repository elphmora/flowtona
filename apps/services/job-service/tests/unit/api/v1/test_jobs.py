"""
tests/unit/api/v1/test_jobs.py

Composition tests for POST /v1/jobs -- the first point authentication,
tenant derivation, authorization, downstream credential propagation,
Client Service validation, snapshot construction, persistence, and
RFC 9457 error translation all run together as one real request path,
not as independently mocked units.

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

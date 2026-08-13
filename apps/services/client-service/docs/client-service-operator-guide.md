# client-service — Operator Guide

## Overview

Client relationship management for the Flowtona platform. See
`client-service-overview.md` for the architecture summary.

**Current status:** Phase 1 is feature-complete and fully runnable.
Domain models, repositories, all three entity services (clients,
sites, contacts), and every route in their HTTP surface are
implemented and tested, along with a full operational layer (health
probes, service metadata, Prometheus metrics). Repositories are
in-memory, not backed by PostgreSQL yet (deliberately deferred).

client-service issues no tokens of its own — it consumes identity-
service's. There is no signing keypair to generate here, unlike
identity-service; instead, client-service needs a *reachable*
identity-service to fetch its public signing key (JWKS) from the first
time an authenticated request arrives. See "Running locally" below for
what this means in practice.

## Prerequisites

- Python 3.12
- `pip`

## Setup

```bash
cd apps/services/client-service
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

`requirements-dev.txt` includes `requirements.txt`, so this installs
both runtime and development dependencies in one step.

## Configuration

Settings load from environment variables with sensible local defaults
(`app/core/config.py`). For local development, create a `.env` file in
`apps/services/client-service/` to override any default. Nothing is
required to run the test suite — every test generates its own
isolated in-memory repositories and a real local JWKS server with a
fresh test keypair, so no external identity-service or configuration
is needed to test the service.

To actually **run** the service against a real identity-service, the
settings that matter are:

| Setting | Default | Purpose |
|---|---|---|
| `JWKS_URL` | `http://localhost:8001/.well-known/jwks.json` | Where to fetch identity-service's public signing key. The local default assumes identity-service running on a different local port than client-service's own. |
| `JWKS_ISSUER` | `https://identity.flowtona.dev` | Expected `iss` claim on a verified token — must match identity-service's configured issuer. |
| `JWKS_AUDIENCE` | `flowtona-api` | Expected `aud` claim on a verified token. |
| `METRICS_ENABLED` | `true` | Whether `/metrics` is mounted at all. |

None of these need to be set for local development if identity-service
is also running locally with its own defaults — the two services'
defaults are designed to match each other out of the box. In
production these settings are expected to come from environment
variables or the deployment platform rather than a local `.env` file;
`JWKS_URL` in particular becomes a Kubernetes Service DNS name, not a
`localhost` URL.

## Running the test suite

```bash
source .venv/bin/activate

# Full suite
pytest tests -q

# With verbose output
pytest tests -v

# A specific layer
pytest tests/unit/repositories -v
pytest tests/unit/services -v
pytest tests/unit/api -v

# The real create_app() integration tier — full HTTP round trips,
# real signed JWTs against a real local JWKS server, cross-tenant and
# cross-client isolation
pytest tests/integration -v

# JWT verification specifically (real ES256 crypto, no mocking)
pytest tests/unit/security -v
```

## Code quality checks

Run all three before committing — the standard check sequence used
throughout this project's development:

```bash
ruff format app/ tests/
ruff check app/ tests/
mypy app tests
```

## Project structure

```
app/
├── api/
│   ├── auth_dependency.py     # Bearer-token verification (get_current_claims)
│   ├── dependencies.py        # ServiceRegistry, build_services(), get_*_service()
│   ├── errors.py              # RFC 9457 exception handler registration
│   ├── permission_dependency.py # require_permission() — 403 on insufficient scope
│   ├── schemas/                # Request/response schemas, one module per resource
│   │   ├── address.py
│   │   ├── client.py
│   │   ├── contact.py
│   │   └── site.py
│   ├── system/                 # /healthz, /readyz, /startupz, /info, /metrics
│   └── v1/                     # Versioned business API
│       ├── clients.py
│       ├── sites.py            # Nested under /v1/clients/{client_id}/sites
│       └── contacts.py         # Nested under /v1/clients/{client_id}/contacts
├── constants/                   # Fixed permission scopes
├── core/                        # Configuration
├── exceptions/                   # Domain exceptions (one file per resource)
├── metrics/
│   ├── auth_metrics.py          # JWT verification failure metrics
│   └── business_metrics.py      # Domain event counters (created, archived, etc.)
├── middleware/
│   ├── metrics.py                # Prometheus HTTP instrumentation
│   └── request_id.py             # Request correlation ID
├── models/                        # Domain entities (Pydantic v2)
├── repositories/                   # Persistence Protocols + in-memory implementations
├── security/
│   └── token_verifier.py           # JWKS-based JWT verification
└── services/                        # Business logic — one service per resource

tests/
├── conftest.py       # Shared JWKS/keypair fixtures — real create_app() integration
│                       # tier and unit-tier security/api tests both inherit from here
├── integration/       # Real create_app(), real HTTP, real signed JWTs
│   ├── auth_helpers.py
│   ├── metrics_helpers.py
│   └── test_*.py       # One behavioral + one metrics file per resource
└── unit/
    ├── api/            # Route-level, schema, and dependency tests (throwaway apps)
    ├── middleware/     # Middleware behavior tests
    ├── models/         # Domain model tests
    ├── repositories/   # Repository behavior tests
    ├── security/       # TokenVerifier tests (real ES256 crypto, local JWKS server)
    └── services/       # Entity service tests
```

## Running locally

```bash
source .venv/bin/activate
uvicorn app.main:create_app --factory --reload
```

**The `--factory` flag is required.** Unlike identity-service,
client-service exposes `create_app()` as a factory function, not a
bare `app` object at module level — `uvicorn app.main:app` will fail
with `Attribute "app" not found in module "app.main"`. This is
deliberate: the same factory function is what lets tests build a
fresh, isolated application instance per test, or inject a pre-seeded
service registry, rather than sharing one process-wide `app` object
the way a bare module-level attribute would require.

The application should report `Application startup complete.` before
serving requests. The service starts on `http://localhost:8000`.
Interactive API docs (Swagger UI) are at `http://localhost:8000/docs`.

**Every business route requires a valid Bearer token.** client-service
does not issue tokens itself, so testing anything beyond the
operational endpoints (`/healthz`, `/readyz`, `/startupz`, `/info`,
`/metrics`, none of which require auth) needs a real access token from
a running identity-service instance — get one via identity-service's
`/v1/auth/signup` or `/v1/auth/login`, then pass it as
`Authorization: Bearer <token>` on requests to client-service. The two
services' default settings are designed to work together locally
without any configuration changes on either side.

### Verifying the service

Once the service has started successfully, confirm the operational
surface is available (none of these require auth):

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
curl http://localhost:8000/startupz
curl http://localhost:8000/info
curl http://localhost:8000/metrics
```

`/readyz`/`/startupz` reporting unhealthy here would indicate a
problem with the application's own startup (service registry
construction), not with identity-service reachability — JWKS fetching
is lazy, so client-service starts successfully and reports ready even
if identity-service isn't reachable yet; the first authenticated
request afterward is what would fail.

### API surface

All business routes are under `/v1`. System/operational routes are
unversioned.

**Clients** (`/v1/clients`)
- `POST /v1/clients`, `GET /v1/clients`
- `GET /v1/clients/{client_id}`, `PATCH /v1/clients/{client_id}`
- `DELETE /v1/clients/{client_id}` (archives — idempotent, not a hard delete)

**Sites** (`/v1/clients/{client_id}/sites`)
- `POST .../sites`, `GET .../sites`
- `GET .../sites/{site_id}`, `PATCH .../sites/{site_id}`
- `DELETE .../sites/{site_id}` (hard delete — not idempotent; a second
  `DELETE` against an already-deleted site returns 404, unlike client
  archive)

**Contacts** (`/v1/clients/{client_id}/contacts`)
- `POST .../contacts`, `GET .../contacts` (optional `?site_id=` filter)
- `GET .../contacts/{contact_id}`, `PATCH .../contacts/{contact_id}`
- `DELETE .../contacts/{contact_id}`

**Operational**
- `GET /healthz`, `GET /readyz`, `GET /startupz`
- `GET /info`
- `GET /metrics`

### Quick manual smoke test

Requires a real access token — see "Running locally" above for how to
get one from identity-service.

```bash
TOKEN="<access token from identity-service login/signup>"

# Create a client
curl -s -X POST http://localhost:8000/v1/clients \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Acme Corp","client_type":"commercial"}' \
  | python3 -m json.tool
```

A successful `201` response confirms the full request pipeline —
routing, JWT verification against identity-service's real JWKS,
validation, business services, and repositories — is functioning
correctly.

```bash
# Confirm request correlation + RFC 9457 error shape on a protected
# route with no Authorization header
curl -s -i http://localhost:8000/v1/clients
```

This example also demonstrates RFC 9457 Problem Details responses and
request correlation via the `X-Request-ID` response header.

**No scripted deployment smoke test exists yet for this service** —
unlike identity-service's `scripts/smoke_test.sh`, client-service only
has `scripts/smoke_test_middleware.py`, a narrower script covering
middleware behavior specifically, not a full pass/fail deployment
verification sequence across the whole API surface. Building the
equivalent of identity-service's smoke-test script is a real, open
item, not something implied to already exist.

## Troubleshooting

### `/readyz` or `/startupz` is unhealthy

This indicates a problem with the application's own startup (building
its internal service registry), not with identity-service
reachability. Check the application logs for the actual startup
error — JWKS fetching is lazy and doesn't block startup, so this isn't
caused by identity-service being unreachable.

### Every business route returns 401

Confirm identity-service is running and reachable at the configured
`JWKS_URL`, and that the token being sent is a real, unexpired access
token from identity-service — not simply present, but actually valid.
`jwt_verification_failures_total{reason}` on `/metrics` shows why
verification is failing without needing to inspect logs — `expired`,
`invalid_claims` (wrong issuer/audience/signature), `key_resolution_failed`
(identity-service unreachable or the token's key ID doesn't match
anything in its published JWKS), and a few others.

### `/metrics` returns no data

Verify the application has started successfully and that the endpoint
returns Prometheus text format:

```bash
curl http://localhost:8000/metrics
```

If empty, confirm `METRICS_ENABLED` hasn't been set to `false`.

## Contributing

This service follows GitFlow (`feature/* → develop → main`). Each
change lands as its own PR against `develop`, with `ruff`, `mypy`, and
the full test suite passing before merge.
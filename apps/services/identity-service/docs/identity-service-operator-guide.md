# identity-service — Operator Guide

## Overview

Authentication and authorization service for the Flowtona platform.
See `identity-service-overview.md` for the architecture summary.

**Current status:** Phase 1 is feature-complete and fully runnable.
Domain models, repositories, all eight entity services, `AuthService`
(the full orchestration layer), and every route in its HTTP surface —
account entry, session lifecycle, email verification, invitations —
are implemented and tested, along with a full operational layer
(health probes, service metadata, JWKS publication, Prometheus
metrics). Repositories are in-memory, not backed by PostgreSQL yet
(deliberately deferred).

## Prerequisites

- Python 3.12
- `pip`

## Setup

```bash
cd apps/services/identity-service
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
```

`requirements-dev.txt` includes `requirements.txt`, so this installs
both runtime and development dependencies in one step.

### Generate a signing keypair

Required before running the service (not required for the test suite,
which generates its own temporary keypairs per test). Without this,
`/readyz` and `/startupz` will correctly report the service as not
ready, and any JWT-issuing endpoint will fail.

```bash
python scripts/generate_signing_keypair.py
```

Writes an ES256 (P-256) keypair to `.flowtona/secrets/` by default
(gitignored — never commit these files). Refuses to overwrite existing
key material; pass `--force` for an intentional rotation.

## Configuration

Settings load from environment variables with sensible local defaults
(`app/core/config.py`). For local development, create a `.env` file in
`apps/services/identity-service/` to override any default. Nothing is
required to run the test suite (all repositories are in-memory, and
tests generate their own isolated keypairs). To actually **run** the
service, the one setting that matters is `SECRETS_DIR`, which defaults
to `.flowtona/secrets` — matching where the keypair-generation script
writes by default, so no override is needed for local development
unless you've placed the keypair somewhere else. In production these
settings are expected to come from environment variables or the
deployment platform rather than a local `.env` file.

## Running the test suite

```bash
source venv/bin/activate

# Full suite
pytest tests -q

# With verbose output
pytest tests -v

# A specific layer
pytest tests/unit/repositories -v
pytest tests/unit/services -v
pytest tests/unit/api -v

# Security-specific tests (password hashing, JWT, token generation)
pytest tests/security -v
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
│   ├── auth_dependency.py   # Bearer-token verification (get_current_claims)
│   ├── dependencies.py      # ServiceRegistry, build_services(), get_*_service()
│   ├── errors.py            # RFC 9457 exception handler registration
│   ├── mappers.py           # Domain objects -> HTTP response schemas
│   ├── system_health.py     # /healthz, /readyz, /startupz
│   ├── system_meta.py       # /info, /.well-known/jwks.json
│   ├── system_metrics.py    # /metrics
│   ├── schemas/              # Request/response schemas, one module per API area
│   │   ├── auth.py
│   │   └── invitations.py
│   └── v1/                   # Versioned business API
│       ├── auth.py           # Account entry + session lifecycle + verification routes
│       ├── invites.py        # Invitation creation + acceptance routes
│       └── router.py         # Assembles all v1 routes
├── constants/                # Fixed roles and permissions
├── core/                     # Configuration
├── exceptions/                # Domain exceptions (one file per entity/concern)
├── middleware/
│   ├── metrics.py            # Prometheus HTTP instrumentation
│   └── request_id.py         # Request correlation ID
├── models/                    # Domain entities (Pydantic v2)
├── repositories/               # Persistence Protocols + in-memory implementations
├── security/                   # Password hashing, JWT primitives, SecretProvider
└── services/                   # Business logic — one service per entity, plus
                                 # AuthService, the orchestration layer

tests/
└── unit/
    ├── api/          # Route-level, schema, mapper, and dependency tests
    ├── repositories/ # Repository behavior tests
    ├── services/      # Entity service and AuthService tests
    └── (root)          # Domain model, config tests
```

## Running locally

```bash
source venv/bin/activate
python scripts/generate_signing_keypair.py   # first time only
uvicorn app.main:app --reload
```

The application should report `Application startup complete.` before
serving requests. The service starts on `http://localhost:8000`.
Interactive API docs (Swagger UI) are at `http://localhost:8000/docs`
— every route can be tried directly from the browser, including
authenticated ones (click "Authorize" and paste in an `access_token`
from a real signup/login response).

### Verifying the service

Once the service has started successfully, confirm the operational
surface is available:

```bash
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
curl http://localhost:8000/startupz
curl http://localhost:8000/info
curl http://localhost:8000/.well-known/jwks.json
curl http://localhost:8000/metrics
```

If `/readyz` or `/startupz` reports the service is not ready, verify a
JWT signing keypair has been generated and that `SECRETS_DIR` points
to the correct location.

### API surface

All business routes are under `/v1`. System/operational routes are
unversioned.

**Account entry** (`/v1/auth/...`)
- `POST /signup`, `POST /login`, `POST /select-tenant`

**Session lifecycle**
- `POST /refresh`, `POST /logout`, `POST /logout-all-for-tenant` (requires Bearer auth)

**Email verification**
- `POST /verify-email` (public), `POST /resend-verification` (requires Bearer auth)

**Invitations**
- `POST /v1/tenants/{tenant_id}/invitations` (requires Bearer auth)
- `POST /v1/invitations/accept-existing-user` (requires Bearer auth)
- `POST /v1/invitations/accept-new-user` (public)

**Operational**
- `GET /healthz`, `GET /readyz`, `GET /startupz`
- `GET /info`
- `GET /.well-known/jwks.json`
- `GET /metrics`

### Quick manual smoke test

```bash
# Signup — returns access_token + refresh_token
curl -s -X POST http://localhost:8000/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"hunter22","display_name":"You","tenant_label":"Test Co"}' \
  | python3 -m json.tool

# Login with the same credentials
curl -s -X POST http://localhost:8000/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"hunter22"}' \
  | python3 -m json.tool
```

A successful signup followed by login confirms the full request
pipeline — routing, validation, business services, password hashing,
JWT generation, and repositories — is functioning correctly.

```bash
# Confirm request correlation + RFC 9457 error shape on a protected
# route with no Authorization header
curl -s -i -X POST http://localhost:8000/v1/auth/logout-all-for-tenant
```

This example also demonstrates RFC 9457 Problem Details responses and
request correlation via the `X-Request-ID` response header.

### Deployment smoke test

`scripts/smoke_test.sh` runs the standard Flowtona deployment
verification sequence against a running identity-service instance —
the operational surface, the full authentication flow (signup, logout,
login, refresh, logout), and the RFC 9457 error shape — with a
pass/fail summary and an exit code suitable for CI.

Run against a locally running service:

```bash
./scripts/smoke_test.sh
```

Expected output on success:

```
=== Smoke testing identity-service at http://localhost:8000 ===
--- Operational surface ---
  PASS: GET /healthz (200, 0.006034s)
  PASS: GET /readyz (200, 0.006686s)
  PASS: GET /startupz (200, 0.007508s)
  PASS: GET /info (200, 0.005331s)
  PASS: GET /.well-known/jwks.json (200, 0.005693s)
  PASS: JWKS response contains at least one key
  PASS: GET /metrics (200, 0.010131s)
  PASS: Metrics output contains http_requests_total
--- Business flow (signup -> logout -> login -> refresh -> logout) ---
  PASS: POST /v1/auth/signup (201, 0.115297s)
  PASS: Signup response contains access_token and refresh_token
  PASS: POST /v1/auth/logout (signup session) (204, 0.004178s)
  PASS: POST /v1/auth/login (200, 0.115690s)
  PASS: POST /v1/auth/refresh (200, 0.004914s)
  PASS: POST /v1/auth/logout (rotated session) (204, 0.003262s)
--- Error handling (RFC 9457 + request correlation) ---
  PASS: Protected route without auth returns 401
  PASS: Error response uses application/problem+json
  PASS: Error response includes X-Request-ID header
  PASS: Error body contains the RFC 9457 core fields
=== Summary: 18 passed, 0 failed ===
```

Run against another deployment:

```bash
BASE_URL=https://identity.example.com ./scripts/smoke_test.sh
```

Requires `curl` and `jq`. Exit codes: `0` — every check passed.
Non-zero — one or more checks failed (see stderr output for which
ones, and why).

```bash
./scripts/smoke_test.sh
SMOKE_EXIT=$?
echo "Smoke-test exit code: $SMOKE_EXIT"
```

## Troubleshooting

### `/readyz` or `/startupz` is unhealthy

The service cannot load its JWT signing keypair. Generate one if
necessary:

```bash
python scripts/generate_signing_keypair.py
```

or verify that `SECRETS_DIR` points to the directory containing the
existing keypair.

### JWT endpoints fail unexpectedly

Confirm the signing keypair exists and matches the configured
`SECRETS_DIR`.

### `/metrics` returns no data

Verify the application has started successfully and that the endpoint
returns Prometheus text format:

```bash
curl http://localhost:8000/metrics
```

## Contributing

This service follows GitFlow (`feature/* → develop → main`). Each
change lands as its own PR against `develop`, with `ruff`, `mypy`, and
the full test suite passing before merge.